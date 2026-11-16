"""Static site: files, single-page fallback, API pass-through, traversal and host checks."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from app.runtime.web import StaticSite

HEADERS = {"X-Content-Type-Options": "nosniff"}


async def inner(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] != "http":
        return
    body = f"inner:{scope['method']}:{scope['path']}".encode()
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": body})


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<html>home</html>", encoding="utf-8")
    (web / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    site = StaticSite(inner, web, hosts={"testserver"}, headers=HEADERS)
    return TestClient(site, base_url="http://testserver")


def test_web_serves_the_index_file_and_assets_with_the_api_headers(client: TestClient) -> None:
    home = client.get("/")
    assert home.status_code == 200 and home.text == "<html>home</html>"
    assert home.headers["x-content-type-options"] == "nosniff"
    assert home.headers["cache-control"] == "no-cache"
    asset = client.get("/assets/app.js")
    assert asset.status_code == 200 and asset.text == "console.log(1)"
    assert "cache-control" not in asset.headers


def test_web_falls_back_to_the_index_for_a_client_route_but_not_for_a_missing_file(
    client: TestClient,
) -> None:
    assert client.get("/projects/abc").text == "<html>home</html>"
    assert client.get("/assets/missing.js").status_code == 404


def test_web_leaves_the_api_and_other_methods_to_the_app(client: TestClient) -> None:
    assert client.get("/api/v1/health").text == "inner:GET:/api/v1/health"
    assert client.get("/openapi.json").text == "inner:GET:/openapi.json"
    assert client.post("/anything").text == "inner:POST:/anything"


@pytest.mark.parametrize(
    "path",
    ["/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt", "/%5c..%5csecret.txt"],
)
def test_web_never_serves_a_file_outside_the_web_folder(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert "secret" not in response.text


def test_web_refuses_a_host_it_does_not_serve(tmp_path: Path) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("x", encoding="utf-8")
    site = StaticSite(inner, web, hosts={"127.0.0.1:1"}, headers=HEADERS)
    response = TestClient(site, base_url="http://evil.invalid").get("/")
    assert response.status_code == 403
