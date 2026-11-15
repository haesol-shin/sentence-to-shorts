"""Fixtures local to the access acceptance tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.access.support import AccessEnv, access_env


@pytest.fixture
def env(app_settings) -> Iterator[AccessEnv]:  # type: ignore[no-untyped-def]
    with access_env(app_settings) as active:
        yield active
