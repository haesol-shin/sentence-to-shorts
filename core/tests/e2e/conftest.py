"""One server per test module, and a paired client for it."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.e2e.support import Api, Server, Studio


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Server]:
    running = Server(tmp_path_factory.mktemp("e2e"))
    running.start()
    try:
        yield running
    finally:
        running.kill()


@pytest.fixture(scope="module")
def studio(server: Server) -> Iterator[Studio]:
    api = Api(server)
    try:
        yield Studio(api)
    finally:
        api.close()
