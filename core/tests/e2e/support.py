"""A server process, an HTTP client that behaves like the paired SPA, and flow helpers."""

from __future__ import annotations

import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx2

from app.settings import Settings
from app.tools.media.adapter import parse_streams, runtime_executable
from tests.media.ffmpeg import find_ffmpeg

CORE = Path(__file__).resolve().parents[2]
JOB_TIMEOUT_S = 300.0
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_until(check: Any, *, timeout_s: float, what: str) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


class Server:
    """One server process on isolated roots under `root`. Start it again after a kill."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.port = free_port()
        self.process: subprocess.Popen[bytes] | None = None
        self.starts = 0
        self.pairing = root / "pairing-0.txt"
        self.stall_ready = root / "stall-ready.txt"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def log(self) -> Path:
        return self.root / "server.log"

    def install_ffmpeg(self) -> None:
        """Put an ffmpeg file where the product's runtime lock says it lives.

        Runtime preparation does the same in a real install; the server then
        resolves it from its own settings, with nothing injected.
        """
        ffmpeg = find_ffmpeg()
        assert ffmpeg is not None
        settings = Settings().model_copy(update={"runtime_dir": self.root / "rt"})
        target = runtime_executable(settings)
        assert target is not None, "the runtime lock names no ffmpeg for this platform"
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.symlink_to(ffmpeg)
        except OSError:
            shutil.copy2(ffmpeg, target)

    def start(self, *, stall_after_clips: int | None = None) -> None:
        self.install_ffmpeg()
        self.pairing = self.root / f"pairing-{self.starts}.txt"
        self.starts += 1
        env = {
            **os.environ,
            "APP_PROFILE": "fixture",
            "APP_DEPLOYMENT": "local",
            "APP_LAN": "0",
            "APP_PORT": str(self.port),
            "APP_DATA_DIR": str(self.data_dir),
            "APP_CACHE_DIR": str(self.root / "cache"),
            "APP_MODEL_DIR": str(self.root / "models"),
            "APP_RUNTIME_DIR": str(self.root / "rt"),
            "E2E_PAIRING_FILE": str(self.pairing),
            "E2E_STALL_READY": str(self.stall_ready),
            "PYTHONUNBUFFERED": "1",
        }
        env.pop("E2E_STALL_AFTER_CLIPS", None)
        if stall_after_clips is not None:
            env["E2E_STALL_AFTER_CLIPS"] = str(stall_after_clips)
        with self.log.open("ab") as log:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "tests.e2e.server"],
                cwd=CORE,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        wait_until(self._healthy, timeout_s=90, what=f"the server to start\n{self.tail()}")

    def _healthy(self) -> bool:
        assert self.process is not None
        if self.process.poll() is not None:
            raise AssertionError(f"the server exited early\n{self.tail()}")
        try:
            return httpx2.get(f"http://127.0.0.1:{self.port}/api/v1/health", timeout=2).is_success
        except httpx2.TransportError:
            return False

    def tail(self) -> str:
        if not self.log.is_file():
            return ""
        return self.log.read_text(encoding="utf-8", errors="replace")[-3000:]

    def kill(self) -> None:
        """Stop without any shutdown step, as a crash or a force quit does."""
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
        if self.process is not None:
            self.process.wait(timeout=30)

    def pairing_code(self) -> str:
        wait_until(self.pairing.is_file, timeout_s=30, what="the pairing URL")
        return self.pairing.read_text(encoding="utf-8").split("#pair=", 1)[1]


class Api:
    """The paired browser: same origin, session cookie, CSRF token, one key per POST."""

    def __init__(self, server: Server) -> None:
        origin = f"http://127.0.0.1:{server.port}"
        self.http = httpx2.Client(
            base_url=origin, headers={"Origin": origin}, timeout=httpx2.Timeout(120.0)
        )
        response = self.http.post("/api/v1/session/pair", json={"code": server.pairing_code()})
        assert response.status_code == 200, response.text
        self.http.headers["X-CSRF-Token"] = response.json()["csrf_token"]

    def close(self) -> None:
        self.http.close()

    def get(self, path: str, *, expect: int = 200, **params: Any) -> Any:
        response = self.http.get(f"/api/v1{path}", params=params or None)
        assert response.status_code == expect, f"{path}: {response.status_code} {response.text}"
        return response.json() if response.content else None

    def post(self, path: str, body: dict[str, Any] | None = None, *, expect: int = 200) -> Any:
        response = self.http.post(
            f"/api/v1{path}", json=body, headers={"Idempotency-Key": uuid.uuid4().hex}
        )
        assert response.status_code == expect, f"{path}: {response.status_code} {response.text}"
        return response.json() if response.content else None

    def download(self, path: str) -> bytes:
        response = self.http.get(f"/api/v1{path}")
        assert response.status_code == 200, f"{path}: {response.status_code}"
        return response.content

    def wait_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Poll the job until it ends. Fails with the job error unless it succeeded."""
        deadline = time.monotonic() + JOB_TIMEOUT_S
        current = job
        while current["state"] not in TERMINAL:
            assert time.monotonic() < deadline, f"job {job['id']} did not end: {current}"
            time.sleep(0.2)
            current = self.get(f"/jobs/{job['id']}")
        assert current["state"] == "succeeded", (current["state"], current["error"])
        return current


class Studio:
    """The user's path through the five steps, one HTTP call per user action."""

    def __init__(self, api: Api) -> None:
        self.api = api

    def new_video(self) -> dict[str, Any]:
        project = self.api.post("/projects", {"title": "e2e", "language": "ko"}, expect=201)
        return self.api.post(
            f"/projects/{project['id']}/videos",
            {"from_video_id": None, "preset_id": None},
            expect=201,
        )

    def head(self, video_id: str) -> dict[str, Any]:
        return self.api.get(f"/videos/{video_id}")["video"]

    def draft(self, video: dict[str, Any]) -> dict[str, Any]:
        job = self.api.post(
            f"/videos/{video['id']}/draft",
            {
                "base_revision": video["revision"],
                "message": "커피 고르는 법",
                "card_id": "just_three",
            },
            expect=202,
        )
        self.api.wait_job(job)
        return self.head(video["id"])

    def confirm(self, video: dict[str, Any], step: str) -> dict[str, Any]:
        return self.api.post(f"/videos/{video['id']}/{step}", {"base_revision": video["revision"]})

    def preview(self, video: dict[str, Any]) -> dict[str, Any]:
        job = self.api.post(
            f"/videos/{video['id']}/previews", {"base_revision": video["revision"]}, expect=202
        )
        self.api.wait_job(job)
        return self.head(video["id"])

    def generate(self, video: dict[str, Any]) -> dict[str, Any]:
        """Start generation and return the finished job."""
        return self.api.wait_job(self.start_generate(video))

    def start_generate(self, video: dict[str, Any]) -> dict[str, Any]:
        return self.api.post(
            f"/videos/{video['id']}/generate", {"base_revision": video["revision"]}, expect=202
        )

    def ready_to_generate(self) -> dict[str, Any]:
        """A new video taken through draft, both confirmations and the scene previews."""
        video = self.draft(self.new_video())
        video = self.confirm(video, "concept/confirm")
        video = self.confirm(video, "script/confirm")
        video = self.preview(video)
        return self.confirm(video, "scenes/confirm")

    def apply_change(self, video: dict[str, Any], ops: list[dict[str, Any]]) -> dict[str, Any]:
        """Propose a change, then apply it with its own confirmation when one is needed."""
        plan = self.api.post(
            f"/videos/{video['id']}/changes",
            {
                "base_revision": video["revision"],
                "source": "direct",
                "target": {"scene_id": None, "pointer": None},
                "ops": ops,
            },
        )
        if plan["status"] == "proposed":
            self.api.post(f"/changes/{plan['id']}/apply", {"base_revision": video["revision"]})
        return self.head(video["id"])


def stage(job: dict[str, Any], name: str) -> dict[str, Any]:
    """The record of one pipeline stage in a finished job."""
    return next(item for item in job["result"]["stages"] if item["stage"] == name)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def probe(path: Path) -> dict[str, Any]:
    """Video size, fps, sample rate and duration, read back by ffmpeg."""
    ffmpeg = find_ffmpeg()
    assert ffmpeg is not None
    done = subprocess.run(
        [str(ffmpeg), "-nostdin", "-hide_banner", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        check=True,
    )
    return parse_streams(done.stderr.decode("utf-8", "replace"))
