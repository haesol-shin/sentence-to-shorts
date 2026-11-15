"""Link download with the bundled yt-dlp executable.

The command line is a fixed argument array. Nothing from the link reaches an
option: the checked URL is the last argument after ``--``, the file name is
issued here, and the user's configuration, plugins, cookies, post-processing
commands and external downloaders are all switched off. The process starts with
an empty PATH and a private home folder, so it cannot find another tool or read
a user's files, and every connection goes through the egress proxy, which refuses
private addresses and counts the bytes. Time and size are capped, and a stop
leaves no file behind.
"""

from __future__ import annotations

import re
import secrets
import shutil
import tempfile
import time
from pathlib import Path

from app.ports import AppError, Cancelled, CancelToken
from app.tools.downloaders.ytdlp.egress import EgressProxy
from app.tools.downloaders.ytdlp.urls import check_url
from app.tools.process import ProcessResult, build_env, run

VIDEO_SUFFIXES = frozenset({".mp4", ".m4v", ".mov", ".webm", ".mkv"})
SCRATCH_SUFFIXES = (".part", ".ytdl", ".temp", ".tmp")
SCAN_EVERY_S = 0.2
STDERR_BYTES = 64 * 1024
SOCKET_TIMEOUT_S = "20"
RETRIES = "2"
# Single-file https formats up to 720p: the native downloader needs no other tool
# and the analysis never looks at more than a small frame.
FORMAT = "b[protocol=https]"
FORMAT_SORT = "res:720"
# Messages the extractors print when the video needs an account, a cookie or a
# way around a protection. They decide ``download_blocked`` and are never stored.
BLOCKED = re.compile(
    r"sign in|log ?in|logged in|cookies|private video|members[- ]only|age[- ]restricted|"
    r"confirm your age|not a bot|authenticat|rate-limit reached|registered users|"
    r"account|captcha",
    re.IGNORECASE,
)


def _argv(executable: Path, *, proxy: str, out_dir: Path, scratch: Path, name: str,
          max_bytes: int, url: str) -> list[str]:
    return [
        str(executable),
        "--ignore-config",
        "--no-config-locations",
        "--no-plugin-dirs",
        "--no-js-runtimes",
        "--no-remote-components",
        "--no-update",
        "--no-exec",
        "--no-cookies",
        "--no-cookies-from-browser",
        "--no-cache-dir",
        "--no-batch-file",
        "--no-playlist",
        "--playlist-items", "1",
        "--max-downloads", "1",
        "--match-filters", "!is_live",
        "--no-write-subs",
        "--no-write-auto-subs",
        "--no-write-thumbnail",
        "--no-write-info-json",
        "--no-write-description",
        "--no-write-comments",
        "--no-embed-subs",
        "--no-embed-thumbnail",
        "--no-embed-metadata",
        "--no-embed-chapters",
        "--no-mtime",
        "--no-progress",
        "--no-warnings",
        "--quiet",
        "--proxy", proxy,
        "--socket-timeout", SOCKET_TIMEOUT_S,
        "--retries", RETRIES,
        "--fragment-retries", "0",
        "--extractor-retries", "1",
        "--max-filesize", str(max_bytes),
        "--format", FORMAT,
        "--format-sort", FORMAT_SORT,
        "-P", str(out_dir),
        "-P", f"temp:{scratch}",
        "-o", f"{name}.%(ext)s",
        "--",
        url,
    ]


def _tree_bytes(root: Path) -> int:
    total = 0
    stack = [root]
    while stack:
        try:
            entries = list(stack.pop().iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    stack.append(entry)
                else:
                    total += entry.stat().st_size
            except OSError:
                continue
    return total


class _Watch:
    """Cancel token for the process: the caller's cancel, the byte budget, the folder size."""

    def __init__(self, cancel: CancelToken, proxy: EgressProxy, root: Path, max_bytes: int) -> None:
        self.cancel = cancel
        self.proxy = proxy
        self.root = root
        self.max_bytes = max_bytes
        self.too_large = False
        self.cancelled = False
        self._next_scan = 0.0

    def is_set(self) -> bool:
        if self.cancel.is_set():
            self.cancelled = True
            return True
        if self.proxy.exceeded:
            self.too_large = True
            return True
        now = time.monotonic()
        if now >= self._next_scan:
            self._next_scan = now + SCAN_EVERY_S
            if _tree_bytes(self.root) > self.max_bytes:
                self.too_large = True
                return True
        return False

    def raise_if_set(self) -> None:
        if self.is_set():
            raise Cancelled("download")

    def wait(self, seconds: float) -> bool:
        return self.cancel.wait(seconds)


class YtDlpDownloader:
    """``DownloaderPort`` over the bundled yt-dlp. Hosted deployments keep it off."""

    def __init__(self, executable: Path | None, *, link_enabled: bool = True) -> None:
        if executable is not None and not executable.is_absolute():
            raise ValueError("the yt-dlp path must be absolute")
        self.executable = executable
        self.link_enabled = link_enabled

    def fetch(
        self,
        url: str,
        *,
        out_dir: Path,
        max_bytes: int,
        max_ms: int,
        cancel: CancelToken,
    ) -> Path:
        if max_bytes < 1 or max_ms < 1:
            raise ValueError("max_bytes and max_ms must be positive")
        if not self.link_enabled:
            raise AppError("link_disabled")
        checked = check_url(url)
        cancel.raise_if_set()
        if self.executable is None or not self.executable.is_file():
            raise AppError("download_failed", detail={"reason": "downloader_unavailable"})
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f"ref_{secrets.token_hex(8)}"
        root = Path(tempfile.mkdtemp(prefix="dl_", dir=out_dir))
        try:
            return self._run(checked, root, out_dir, name, max_bytes, max_ms, cancel)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            for leftover in out_dir.glob(f"{name}.*"):
                if leftover.suffix in SCRATCH_SUFFIXES:
                    leftover.unlink(missing_ok=True)

    def _run(self, url: str, root: Path, out_dir: Path, name: str, max_bytes: int, max_ms: int,
             cancel: CancelToken) -> Path:
        assert self.executable is not None
        home = root / "home"
        scratch = root / "scratch"
        empty = root / "bin"
        for folder in (home, scratch, empty):
            folder.mkdir()
        env = build_env(
            {
                "PATH": str(empty),
                "HOME": str(home),
                "USERPROFILE": str(home),
                "TMPDIR": str(scratch),
                "TMP": str(scratch),
                "TEMP": str(scratch),
            }
        )
        started = time.monotonic()
        with EgressProxy(max_bytes=max_bytes) as proxy:
            watch = _Watch(cancel, proxy, out_dir, max_bytes)
            result = run(
                _argv(self.executable, proxy=proxy.url, out_dir=out_dir, scratch=scratch,
                      name=name, max_bytes=max_bytes, url=url),
                cwd=home,
                env=env,
                timeout_s=max_ms / 1000,
                max_stdout_bytes=STDERR_BYTES,
                max_stderr_bytes=STDERR_BYTES,
                cancel=watch,
            )
            denied = proxy.denied
        if watch.too_large:
            self._discard(out_dir, name)
            raise AppError("download_too_large", detail={"max_bytes": max_bytes})
        if watch.cancelled or result.cancelled:
            self._discard(out_dir, name)
            raise Cancelled("download")
        if result.timed_out:
            self._discard(out_dir, name)
            raise AppError("download_failed", detail={"reason": "timeout", "max_ms": max_ms})
        return self._outcome(result, denied, out_dir, name, max_bytes, started)

    def _outcome(self, result: ProcessResult, denied: list[str], out_dir: Path, name: str,
                 max_bytes: int, started: float) -> Path:
        finished = [
            path for path in out_dir.glob(f"{name}.*")
            if path.suffix not in SCRATCH_SUFFIXES and path.is_file() and not path.is_symlink()
        ]
        # --max-downloads ends the run with exit code 101 after the one file arrived.
        if len(finished) == 1 and result.returncode in (0, 101) and not denied:
            path = finished[0]
            if path.suffix.lower() not in VIDEO_SUFFIXES:
                self._discard(out_dir, name)
                raise AppError("download_failed", detail={"reason": "format"})
            if path.stat().st_size > max_bytes:
                self._discard(out_dir, name)
                raise AppError("download_too_large", detail={"max_bytes": max_bytes})
            return path
        self._discard(out_dir, name)
        if denied:
            raise AppError("url_not_allowed", detail={"reason": "redirect", "rule": denied[0]})
        message = result.stderr.decode("utf-8", "replace")
        if BLOCKED.search(message):
            raise AppError("download_blocked")
        raise AppError(
            "download_failed",
            detail={"reason": "exit", "exit": result.returncode,
                    "ms": int((time.monotonic() - started) * 1000)},
        )

    @staticmethod
    def _discard(out_dir: Path, name: str) -> None:
        for path in out_dir.glob(f"{name}.*"):
            path.unlink(missing_ok=True)
