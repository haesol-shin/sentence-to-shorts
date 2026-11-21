"""The host CPU must not depend on environment variables a bare Windows user shell lacks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.runtime import lock
from app.tools.media import adapter as media


@pytest.mark.parametrize(
    ("tag", "expected"),
    [("win-amd64", "x86_64"), ("win-arm64", "aarch64")],
)
def test_windows_cpu_comes_from_the_interpreter_not_the_environment(
    monkeypatch: pytest.MonkeyPatch, tag: str, expected: str
) -> None:
    # `platform.machine()` answers "" on Windows when PROCESSOR_ARCHITECTURE is not set.
    monkeypatch.setattr(lock, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(media, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(lock.platform, "machine", lambda: "")
    monkeypatch.setattr(lock.sysconfig, "get_platform", lambda: tag)
    assert lock.host_platform() == ("windows", expected)
    assert media._platform() == ("windows", expected)


def test_linux_cpu_still_comes_from_the_machine_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lock, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(media, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(lock.platform, "machine", lambda: "aarch64")
    assert lock.host_platform() == ("linux", "aarch64")
    assert media._platform() == ("linux", "aarch64")
