"""Shared builders for the reference tests: a fake job context, a fake yt-dlp, synthetic media."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.ports import Cancelled, LlmRequest, LlmResult
from app.schemas.common import PERSONAL_OWNER_ID
from app.schemas.job import Effort, Stage, Usage
from app.schemas.video import Video
from tests.media import ffmpeg
from tests.media.scenes import load


class Cancel:
    def __init__(self) -> None:
        self.event = threading.Event()

    def is_set(self) -> bool:
        return self.event.is_set()

    def raise_if_set(self) -> None:
        if self.event.is_set():
            raise Cancelled()

    def wait(self, seconds: float) -> bool:
        return self.event.wait(seconds)


@dataclass
class Context:
    """The part of ``JobContext`` the reference service uses."""

    job_dir: Path
    owner_id: str = PERSONAL_OWNER_ID
    input: dict[str, Any] = field(default_factory=dict)
    cancel: Cancel = field(default_factory=Cancel)
    deadline: float = field(default_factory=lambda: time.monotonic() + 120)
    stages: list[Stage] = field(default_factory=list)
    usages: list[Usage] = field(default_factory=list)

    def progress(self, **_: Any) -> None:
        return None

    def stage(self, stage: Stage):  # type: ignore[no-untyped-def]
        from contextlib import contextmanager

        @contextmanager
        def scope():  # type: ignore[no-untyped-def]
            self.stages.append(stage)
            yield

        return scope()

    def checkpoint(self, record: Any) -> None:
        return None

    def record_usage(self, usage: Usage) -> None:
        self.usages.append(usage)


def usage() -> Usage:
    return Usage(
        stage=Stage.ref_llm, provider="fixture", model="synthetic", effort=Effort.medium,
        input_tokens=1, output_tokens=1, cache_read_tokens=None, cost_usd=None,
        wall_ms=1, retries=0,
    )


class ScriptedLlm:
    """Answers with queued parsed objects and records every request."""

    def __init__(self, *answers: dict[str, Any] | None) -> None:
        self.answers = list(answers)
        self.requests: list[LlmRequest] = []

    def complete(
        self, req: LlmRequest, *, owner_id: str, cancel: Any, deadline: float
    ) -> LlmResult:
        self.requests.append(req)
        parsed = self.answers.pop(0)
        return LlmResult(
            text=json.dumps(parsed or {}), parsed=parsed, usage=usage()
        )

    def auth_state(self, owner_id: str) -> str:
        return "ok"


def draft_video() -> Video:
    """The contract fixture video reset to the concept stage: no script, no scenes."""
    raw = load("video_ko_just_three.json")
    raw["stage"] = "draft"
    raw["script"] = None
    raw["scenes"] = {}
    raw["scene_order"] = []
    raw["settings"]["format"]["scene_count"] = 8
    return Video.model_validate(raw)


def make_reference(path: Path, *, with_audio: bool = True, seconds: int = 3) -> Path:
    """A synthetic mp4: a new colour every second and, optionally, a steady tone."""
    executable = ffmpeg.find_ffmpeg()
    assert executable is not None
    colors = ["red", "blue", "green", "yellow", "white", "black"][:seconds]
    args: list[str] = [str(executable), "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    for color in colors:
        args += ["-f", "lavfi", "-i", f"color=c={color}:s=160x288:r=10:d=1"]
    if with_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=16000:duration={seconds}"]
    chain = "".join(f"[{index}:v]" for index in range(len(colors)))
    args += ["-filter_complex", f"{chain}concat=n={len(colors)}:v=1:a=0[v]", "-map", "[v]"]
    if with_audio:
        args += ["-map", f"{len(colors)}:a", "-c:a", "aac"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(args, check=True, capture_output=True)
    return path


FAKE_YTDLP = '''#!{python}
import json, os, sys, time
args = sys.argv[1:]
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "argv.json"), "w") as handle:
    json.dump({{"argv": args, "env": dict(os.environ), "cwd": os.getcwd()}}, handle)
url = args[args.index("--") + 1]
out_dir = args[args.index("-P") + 1]
template = args[args.index("-o") + 1]
proxy = args[args.index("--proxy") + 1]
mode = url.split("mode=", 1)[1].split("&", 1)[0] if "mode=" in url else "ok"
name = template.replace("%(ext)s", "mp4")
if mode == "login":
    sys.stderr.write("ERROR: Sign in to confirm you're not a bot. Use --cookies-from-browser\\n")
    sys.exit(1)
if mode == "fail":
    sys.stderr.write("ERROR: Unsupported URL\\n")
    sys.exit(1)
if mode in ("redirect", "metadata", "loopback"):
    import socket
    targets = {{"redirect": "localhost", "metadata": "169.254.169.254", "loopback": "127.0.0.1"}}
    target = targets[mode]
    host, port = proxy.split("//", 1)[1].split(":")
    sock = socket.create_connection((host, int(port)), timeout=5)
    request = "CONNECT %s:443 HTTP/1.1\\r\\nHost: %s:443\\r\\n\\r\\n" % (target, target)
    sock.sendall(request.encode())
    reply = sock.recv(200).decode("latin-1")
    sys.stderr.write("tunnel: " + reply.splitlines()[0] + "\\n")
    sys.exit(1)
if mode == "big":
    with open(os.path.join(out_dir, name), "wb") as handle:
        handle.write(b"x" * 8000)
    time.sleep(30)
    sys.exit(0)
if mode == "slow":
    time.sleep(30)
    sys.exit(0)
if mode == "wait":
    with open(os.path.join(out_dir, name + ".part"), "wb") as handle:
        handle.write(b"partial")
    time.sleep(30)
    sys.exit(0)
if mode == "text":
    name = template.replace("%(ext)s", "html")
with open(os.path.join(out_dir, name), "wb") as handle:
    handle.write(b"synthetic video bytes")
sys.exit(101 if mode == "ok" else 0)
'''


def fake_ytdlp(directory: Path) -> Path:
    """An executable that stands in for yt-dlp and acts on ``mode=`` in the link.

    Windows cannot start a file by its shebang, so there the script is started
    through the interpreter by a batch file, and the batch file is the executable.
    """
    directory.mkdir(parents=True, exist_ok=True)
    body = FAKE_YTDLP.format(python=sys.executable)
    if os.name == "nt":
        source = directory / "yt_dlp_fake.py"
        source.write_text(body, encoding="utf-8")
        batch = directory / "yt-dlp.cmd"
        batch.write_text(f'@echo off\r\n"{sys.executable}" "{source}" %*\r\n', encoding="utf-8")
        return batch
    script = directory / "yt-dlp"
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def last_call(directory: Path) -> dict[str, Any]:
    return json.loads((directory / "argv.json").read_text(encoding="utf-8"))


