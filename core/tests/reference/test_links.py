"""Link policy: exact HTTPS hosts only, and a proxy that refuses private addresses."""

from __future__ import annotations

import socket
import threading

import pytest

from app.ports import AppError
from app.tools.downloaders.ytdlp.egress import EgressProxy, is_public
from app.tools.downloaders.ytdlp.urls import check_url

GOOD = [
    "https://www.youtube.com/watch?v=abc",
    "https://youtu.be/abc",
    "https://www.instagram.com/reel/abc/",
    "https://www.tiktok.com/@user/video/1",
    "https://vm.tiktok.com/abc/",
]


@pytest.mark.parametrize("url", GOOD)
def test_20_link_allows_the_platform_hosts(url: str) -> None:
    assert check_url(url).startswith("https://")


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("https://example.com/video.mp4", "host"),
        ("https://youtube.com.evil.example/watch?v=1", "host"),
        ("https://notyoutube.com/watch?v=1", "host"),
        ("https://user:pass@www.youtube.com/watch?v=1", "userinfo"),
        ("https://www.youtube.com@evil.example/watch?v=1", "userinfo"),
        ("https://www.youtube.com:8443/watch?v=1", "port"),
        ("https://127.0.0.1/watch", "ip_literal"),
        ("https://169.254.169.254/latest/meta-data", "ip_literal"),
        ("https://[::1]/watch", "ip_literal"),
        ("https://2130706433/watch", "host"),
        ("http://www.youtube.com/watch?v=1", "scheme"),
        ("file:///etc/passwd", "scheme"),
        ("ftp://www.youtube.com/x", "scheme"),
        ("https://www.youtube.com/watch?v=1 --exec id", "characters"),
        ("https://www.youtube.com\\@evil.example/", "characters"),
        ("https://www.youtube.com/\u00e9", "characters"),
        ("", "length"),
    ],
)
def test_20_link_refuses_hosts_outside_the_allowlist(url: str, reason: str) -> None:
    with pytest.raises(AppError) as caught:
        check_url(url)
    assert caught.value.code == "url_not_allowed"
    assert caught.value.detail["reason"] == reason
    assert not url or url not in str(caught.value.detail)


def test_20_link_refuses_a_long_url() -> None:
    with pytest.raises(AppError):
        check_url("https://www.youtube.com/watch?v=" + "a" * 600)


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("93.184.216.34", True),
        ("2606:2800:220:1:248:1893:25c8:1946", True),
        ("127.0.0.1", False),
        ("10.0.0.5", False),
        ("172.16.3.4", False),
        ("192.168.1.1", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("0.0.0.0", False),
        ("::1", False),
        ("fe80::1", False),
        ("fc00::1", False),
        ("::ffff:127.0.0.1", False),
        ("::ffff:10.1.2.3", False),
        ("64:ff9b::7f00:1", False),
        ("224.0.0.1", False),
        ("not an address", False),
    ],
)
def test_20_private_addresses_are_not_public(address: str, public: bool) -> None:
    assert is_public(address) is public


def _connect_request(proxy: EgressProxy, target: str) -> tuple[str, socket.socket]:
    host, port = proxy.url.split("//", 1)[1].split(":")
    sock = socket.create_connection((host, int(port)), timeout=5)
    sock.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = sock.recv(200)
        if not chunk:
            break
        head += chunk
    return head.split(b"\r\n", 1)[0].decode(), sock


class Upstream:
    """A local server that stands in for the remote host behind an allowed name."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(4)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server.getsockname()[1]

    def _serve(self) -> None:
        while True:
            try:
                client, _ = self.server.accept()
            except OSError:
                return
            try:
                client.sendall(self.payload)
            except OSError:
                pass
            finally:
                client.close()

    def close(self) -> None:
        self.server.close()


def test_20_proxy_refuses_a_name_that_resolves_to_a_private_address() -> None:
    dialled: list[str] = []

    def connect(address: str, port: int) -> socket.socket:
        dialled.append(address)
        raise AssertionError("a refused tunnel must not dial")

    with EgressProxy(
        max_bytes=1000,
        resolve=lambda host: ["10.0.0.7"] if host == "redirect.example.invalid" else ["8.8.8.8"],
        connect=connect,
    ) as proxy:
        status, sock = _connect_request(proxy, "redirect.example.invalid:443")
        sock.close()
        assert status.startswith("HTTP/1.1 403")
        assert proxy.denied == ["private_address"]
    assert dialled == []


def test_20_proxy_refuses_one_private_answer_among_public_ones() -> None:
    with EgressProxy(
        max_bytes=1000,
        resolve=lambda host: ["8.8.8.8", "192.168.0.9"],
        connect=lambda address, port: (_ for _ in ()).throw(AssertionError("no dial")),
    ) as proxy:
        status, sock = _connect_request(proxy, "mixed.example.invalid:443")
        sock.close()
        assert status.startswith("HTTP/1.1 403")


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        ("example.invalid:80", "port"),
        ("example.invalid:8443", "port"),
        ("127.0.0.1:443", "private_address"),
    ],
)
def test_20_proxy_serves_https_tunnels_to_public_hosts_only(target: str, reason: str) -> None:
    def resolve(host: str) -> list[str]:
        return [host] if host[0].isdigit() else ["8.8.8.8"]

    with EgressProxy(max_bytes=1000, resolve=resolve) as proxy:
        status, sock = _connect_request(proxy, target)
        sock.close()
        assert status.startswith("HTTP/1.1 403")
        assert proxy.denied == [reason]


def test_20_proxy_tunnels_a_public_host_and_counts_the_bytes() -> None:
    upstream = Upstream(b"y" * 600)
    dialled: list[tuple[str, int]] = []

    def connect(address: str, port: int) -> socket.socket:
        dialled.append((address, port))
        return socket.create_connection(("127.0.0.1", upstream.port), timeout=5)

    try:
        with EgressProxy(
            max_bytes=1000, resolve=lambda host: ["8.8.8.8"], connect=connect
        ) as proxy:
            status, sock = _connect_request(proxy, "media.example.invalid:443")
            data = b""
            while chunk := sock.recv(4096):
                data += chunk
            sock.close()
            assert status.startswith("HTTP/1.1 200")
            assert len(data) == 600
            assert proxy.received_bytes == 600
            assert not proxy.exceeded
    finally:
        upstream.close()
    assert dialled == [("8.8.8.8", 443)]


def test_20_proxy_stops_a_tunnel_that_passes_the_byte_budget() -> None:
    upstream = Upstream(b"z" * 5000)
    try:
        with EgressProxy(
            max_bytes=1000,
            resolve=lambda host: ["8.8.8.8"],
            connect=lambda address, port: socket.create_connection(("127.0.0.1", upstream.port)),
        ) as proxy:
            status, sock = _connect_request(proxy, "media.example.invalid:443")
            received = 0
            while chunk := sock.recv(4096):
                received += len(chunk)
            sock.close()
            assert status.startswith("HTTP/1.1 200")
            assert received <= 1000
            assert proxy.exceeded
    finally:
        upstream.close()
