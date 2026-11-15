"""Link download: a fixed command line, refused redirects, size and time caps, no leftovers."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from app.ports import AppError, Cancelled
from app.tools.downloaders.adapter import create, create_skeleton
from app.tools.downloaders.ytdlp.downloader import YtDlpDownloader
from tests.reference.support import Cancel, fake_ytdlp, last_call

LINK = "https://www.youtube.com/watch?v=abc&mode="
MAX_BYTES = 4000
MAX_MS = 20_000


@pytest.fixture
def downloader(tmp_path: Path) -> YtDlpDownloader:
    return YtDlpDownloader(fake_ytdlp(tmp_path / "tool").resolve())


def _fetch(
    downloader: YtDlpDownloader,
    tmp_path: Path,
    mode: str = "ok",
    *,
    max_ms: int = MAX_MS,
    cancel: Cancel | None = None,
) -> Path:
    return downloader.fetch(
        LINK + mode,
        out_dir=tmp_path / "out",
        max_bytes=MAX_BYTES,
        max_ms=max_ms,
        cancel=cancel or Cancel(),
    )


def _left(tmp_path: Path) -> list[str]:
    return sorted(path.name for path in (tmp_path / "out").iterdir())


def test_20_download_returns_the_app_named_file(
    downloader: YtDlpDownloader, tmp_path: Path
) -> None:
    path = _fetch(downloader, tmp_path)
    assert path.parent == tmp_path / "out"
    assert path.suffix == ".mp4" and path.name.startswith("ref_")
    assert path.read_bytes() == b"synthetic video bytes"
    assert _left(tmp_path) == [path.name]


def test_20_download_runs_a_fixed_command_line(
    downloader: YtDlpDownloader, tmp_path: Path
) -> None:
    _fetch(downloader, tmp_path)
    call = last_call(tmp_path / "tool")
    argv = call["argv"]
    for flag in (
        "--ignore-config", "--no-config-locations", "--no-plugin-dirs", "--no-exec",
        "--no-cookies", "--no-cookies-from-browser", "--no-playlist", "--no-write-subs",
        "--no-write-auto-subs", "--no-write-thumbnail", "--no-js-runtimes",
        "--no-remote-components", "--no-update", "--no-batch-file",
    ):
        assert flag in argv
    forbidden = {"--exec", "--cookies", "--downloader", "--plugin-dirs", "--config-locations"}
    assert not forbidden & set(argv)
    assert argv[-2:] == ["--", LINK + "ok"]
    assert argv[argv.index("--max-filesize") + 1] == str(MAX_BYTES)
    assert argv[argv.index("--proxy") + 1].startswith("http://127.0.0.1:")
    assert argv[argv.index("-o") + 1].startswith("ref_") and "abc" not in argv[argv.index("-o") + 1]


def test_20_download_process_sees_no_path_and_a_private_home(
    downloader: YtDlpDownloader, tmp_path: Path
) -> None:
    _fetch(downloader, tmp_path)
    call = last_call(tmp_path / "tool")
    env = call["env"]
    assert Path(env["PATH"]).name == "bin" and os.pathsep not in env["PATH"]
    assert Path(env["HOME"]) != Path.home()
    assert Path(call["cwd"]).resolve() == Path(env["HOME"]).resolve()
    assert not {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "ANTHROPIC_API_KEY"} & set(env)


@pytest.mark.parametrize("mode", ["redirect", "metadata", "loopback"])
def test_20_download_refuses_a_redirect_to_a_private_address(
    downloader: YtDlpDownloader, tmp_path: Path, mode: str
) -> None:
    with pytest.raises(AppError) as caught:
        _fetch(downloader, tmp_path, mode)
    assert caught.value.code == "url_not_allowed"
    assert caught.value.detail["reason"] == "redirect"
    assert _left(tmp_path) == []


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video.mp4",
        "https://127.0.0.1/video.mp4",
        "http://www.youtube.com/watch?v=1",
        "https://user@www.youtube.com/watch?v=1",
        "https://www.youtube.com:444/watch?v=1",
    ],
)
def test_20_download_refuses_a_link_before_any_process_starts(
    downloader: YtDlpDownloader, tmp_path: Path, url: str
) -> None:
    with pytest.raises(AppError) as caught:
        downloader.fetch(url, out_dir=tmp_path / "out", max_bytes=1, max_ms=1000, cancel=Cancel())
    assert caught.value.code == "url_not_allowed"
    assert not (tmp_path / "tool" / "argv.json").exists()


def test_20_download_login_required_is_download_blocked(
    downloader: YtDlpDownloader, tmp_path: Path
) -> None:
    with pytest.raises(AppError) as caught:
        _fetch(downloader, tmp_path, "login")
    assert caught.value.code == "download_blocked"
    assert "abc" not in str(caught.value.detail)
    assert _left(tmp_path) == []


def test_20_download_other_failures_are_download_failed(
    downloader: YtDlpDownloader, tmp_path: Path
) -> None:
    with pytest.raises(AppError) as caught:
        _fetch(downloader, tmp_path, "fail")
    assert caught.value.code == "download_failed"
    assert _left(tmp_path) == []


def test_20_download_a_page_instead_of_a_video_is_refused(
    downloader: YtDlpDownloader, tmp_path: Path
) -> None:
    with pytest.raises(AppError) as caught:
        _fetch(downloader, tmp_path, "text")
    assert caught.value.code == "download_failed"
    assert _left(tmp_path) == []


def test_20_download_over_the_byte_limit_is_refused_and_removed(
    downloader: YtDlpDownloader, tmp_path: Path
) -> None:
    started = time.monotonic()
    with pytest.raises(AppError) as caught:
        _fetch(downloader, tmp_path, "big")
    assert caught.value.code == "download_too_large"
    assert time.monotonic() - started < 15
    assert _left(tmp_path) == []


def test_20_download_over_the_time_limit_is_stopped_and_removed(
    downloader: YtDlpDownloader, tmp_path: Path
) -> None:
    started = time.monotonic()
    with pytest.raises(AppError) as caught:
        _fetch(downloader, tmp_path, "slow", max_ms=1000)
    assert caught.value.code == "download_failed"
    assert caught.value.detail["reason"] == "timeout"
    assert time.monotonic() - started < 15
    assert _left(tmp_path) == []


def test_20_download_cancel_stops_the_process_and_leaves_nothing(
    downloader: YtDlpDownloader, tmp_path: Path
) -> None:
    cancel = Cancel()
    threading.Timer(1.0, cancel.event.set).start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        _fetch(downloader, tmp_path, "wait", cancel=cancel)
    assert time.monotonic() - started < 15
    assert _left(tmp_path) == []


def test_20_download_is_off_in_a_hosted_deployment(tmp_path: Path) -> None:
    hosted = YtDlpDownloader(fake_ytdlp(tmp_path / "tool").resolve(), link_enabled=False)
    with pytest.raises(AppError) as caught:
        _fetch(hosted, tmp_path)
    assert caught.value.code == "link_disabled"
    assert not (tmp_path / "tool" / "argv.json").exists()


def test_20_download_without_a_locked_executable_fails_cleanly(tmp_path: Path) -> None:
    with pytest.raises(AppError) as caught:
        _fetch(YtDlpDownloader(None), tmp_path)
    assert caught.value.code == "download_failed"
    assert caught.value.detail["reason"] == "downloader_unavailable"


def test_20_download_adapter_follows_the_deployment_and_the_runtime_lock(
    app_settings,  # type: ignore[no-untyped-def]
) -> None:
    local = create(app_settings)
    assert local.link_enabled and local.executable is None
    app_settings.deployment = "hosted"
    assert not create(app_settings).link_enabled
    with pytest.raises(NotImplementedError):
        create_skeleton(app_settings).fetch(
            LINK, out_dir=Path("."), max_bytes=1, max_ms=1, cancel=Cancel()
        )
