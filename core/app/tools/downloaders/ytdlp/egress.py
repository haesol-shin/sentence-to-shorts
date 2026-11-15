"""A local CONNECT proxy that every download connection has to go through.

The downloader cannot be told which redirects to follow, so the connection
itself is checked. The proxy resolves each target name once, refuses the
tunnel unless every answer is a public address, and dials that address, so a
redirect to a private host and a DNS answer that changes between check and use
both fail. Only HTTPS tunnels to port 443 are served. The bytes that come back
are counted across all tunnels, and the budget stops them when it runs out.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import socketserver
import threading
from collections.abc import Callable

HEAD_LIMIT = 8192
CONNECT_TIMEOUT_S = 10.0
IO_TIMEOUT_S = 30.0
CHUNK = 65536
_HOST = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")

Resolver = Callable[[str], list[str]]
Connector = Callable[[str, int], socket.socket]


def is_public(address: str) -> bool:
    """True for a globally routable address, judging embedded IPv4 addresses too."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = [ip.ipv4_mapped, ip.sixtofour]
        if ip.teredo is not None:
            embedded.append(ip.teredo[1])
        if ip in ipaddress.ip_network("64:ff9b::/96"):
            embedded.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if any(item is not None and not item.is_global for item in embedded):
            return False
    return ip.is_global and not ip.is_multicast


def resolve_host(host: str) -> list[str]:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return [host]
    found = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return sorted({str(item[4][0]) for item in found})


def connect_address(address: str, port: int) -> socket.socket:
    return socket.create_connection((address, port), timeout=CONNECT_TIMEOUT_S)


class EgressProxy:
    """Loopback proxy with a shared download budget. Use it as a context manager."""

    def __init__(
        self,
        *,
        max_bytes: int,
        resolve: Resolver = resolve_host,
        connect: Connector = connect_address,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self._resolve = resolve
        self._connect = connect
        self._lock = threading.Lock()
        self._received = 0
        self._denied: list[str] = []
        self._exceeded = threading.Event()
        self._sockets: set[socket.socket] = set()
        proxy = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                proxy._serve(self.request)  # noqa: SLF001

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self._server = Server(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    @property
    def denied(self) -> list[str]:
        with self._lock:
            return list(self._denied)

    @property
    def exceeded(self) -> bool:
        return self._exceeded.is_set()

    @property
    def received_bytes(self) -> int:
        with self._lock:
            return self._received

    def __enter__(self) -> EgressProxy:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        with self._lock:
            open_sockets = list(self._sockets)
        for item in open_sockets:
            self._shut(item)

    def _deny(self, reason: str) -> None:
        with self._lock:
            self._denied.append(reason)

    @staticmethod
    def _shut(item: socket.socket) -> None:
        try:
            item.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            item.close()
        except OSError:
            pass

    @staticmethod
    def _reply(client: socket.socket, status: str) -> None:
        try:
            client.sendall(f"HTTP/1.1 {status}\r\nConnection: close\r\n\r\n".encode("ascii"))
        except OSError:
            pass

    @staticmethod
    def _read_head(client: socket.socket) -> tuple[bytes, bytes] | None:
        data = b""
        while b"\r\n\r\n" not in data:
            if len(data) > HEAD_LIMIT:
                return None
            chunk = client.recv(CHUNK)
            if not chunk:
                return None
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        return head, rest

    def _target(self, head: bytes) -> tuple[str, str] | None:
        """The checked host and the address to dial, or None after a denial."""
        words = head.split(b"\r\n", 1)[0].decode("latin-1").split(" ")
        if len(words) != 3 or words[0] != "CONNECT":
            self._deny("not_tunnel")
            return None
        host, separator, port = words[1].rpartition(":")
        host = host.strip("[]").lower()
        if not separator or port != "443":
            self._deny("port")
            return None
        if not _HOST.fullmatch(host) and not _is_ip(host):
            self._deny("host")
            return None
        try:
            addresses = self._resolve(host)
        except OSError:
            self._deny("unresolved")
            return None
        if not addresses or not all(is_public(address) for address in addresses):
            self._deny("private_address")
            return None
        return host, addresses[0]

    def _serve(self, client: socket.socket) -> None:
        client.settimeout(IO_TIMEOUT_S)
        upstream: socket.socket | None = None
        try:
            parsed = self._read_head(client)
            if parsed is None:
                self._deny("request")
                self._reply(client, "400 Bad Request")
                return
            head, early = parsed
            target = self._target(head)
            if target is None:
                self._reply(client, "403 Forbidden")
                return
            try:
                upstream = self._connect(target[1], 443)
            except OSError:
                self._reply(client, "502 Bad Gateway")
                return
            upstream.settimeout(IO_TIMEOUT_S)
            with self._lock:
                self._sockets.update((client, upstream))
            self._reply(client, "200 Connection established")
            self._pump(client, upstream, early)
        except OSError:
            pass
        finally:
            for item in (client, upstream):
                if item is not None:
                    self._shut(item)
                    with self._lock:
                        self._sockets.discard(item)

    def _pump(self, client: socket.socket, upstream: socket.socket, early: bytes) -> None:
        def forward() -> None:
            try:
                if early:
                    upstream.sendall(early)
                while True:
                    chunk = client.recv(CHUNK)
                    if not chunk:
                        break
                    upstream.sendall(chunk)
            except OSError:
                pass
            finally:
                try:
                    upstream.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        sender = threading.Thread(target=forward, daemon=True)
        sender.start()
        try:
            while True:
                chunk = upstream.recv(CHUNK)
                if not chunk:
                    break
                with self._lock:
                    self._received += len(chunk)
                    over = self._received > self.max_bytes
                if over:
                    self._exceeded.set()
                    break
                client.sendall(chunk)
        except OSError:
            pass
        finally:
            self._shut(client)
            self._shut(upstream)
            sender.join(timeout=5)


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True
