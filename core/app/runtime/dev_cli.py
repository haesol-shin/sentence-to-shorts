"""Check the official Claude CLI for the developer distribution.

The app only asks the CLI itself: is it installed, which version, does it report a login.
It never opens or reads the CLI's credential files, and it ignores the CLI's output, so no
account detail can reach a log. The CLI is optional: other adapters work without it. A
release distribution never calls this module.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

GUIDE_URL = "https://docs.anthropic.com/en/docs/claude-code/getting-started"
EXECUTABLE = "claude"
TIMEOUT_S = 20.0
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_KEEP_ENV = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "CLAUDE_CONFIG_DIR",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
)

State = Literal["ok", "missing", "too_old", "not_logged_in", "unknown"]


@dataclass(frozen=True)
class CliStatus:
    state: State
    version: str | None
    message: str


def _run(argv: Sequence[str]) -> tuple[int | None, str]:
    """Exit code and stdout of the command; (None, "") when it cannot run or hangs."""
    environment = {key: os.environ[key] for key in _KEEP_ENV if key in os.environ}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=TIMEOUT_S,
            check=False,
            env=environment,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return completed.returncode, completed.stdout.decode("utf-8", "replace")


def parse_version(text: str) -> tuple[int, int, int] | None:
    found = _VERSION.search(text)
    return None if found is None else (int(found[1]), int(found[2]), int(found[3]))


def check_claude_cli(
    minimum: tuple[int, int, int],
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[[Sequence[str]], tuple[int | None, str]] = _run,
) -> CliStatus:
    """Presence, version and login state of the official CLI, with a next step for each."""
    executable = which(EXECUTABLE)
    if executable is None:
        return CliStatus(
            "missing",
            None,
            f"The official Claude CLI is not installed. It is optional. Install it: {GUIDE_URL}",
        )
    code, output = run([executable, "--version"])
    version = parse_version(output) if code == 0 else None
    if version is None:
        return CliStatus(
            "unknown",
            None,
            f"The Claude CLI did not report a version. Follow the setup guide: {GUIDE_URL}",
        )
    shown = ".".join(str(part) for part in version)
    if version < minimum:
        wanted = ".".join(str(part) for part in minimum)
        return CliStatus(
            "too_old",
            shown,
            f"Claude CLI {shown} is older than {wanted}. Update it as in {GUIDE_URL}",
        )
    code, _ignored = run([executable, "auth", "status"])
    if code == 0:
        return CliStatus("ok", shown, f"Claude CLI {shown} is installed and signed in.")
    if code is None:
        return CliStatus("unknown", shown, "The Claude CLI did not answer the login check.")
    return CliStatus(
        "not_logged_in",
        shown,
        "The Claude CLI is not signed in. Run `claude auth login` in a terminal.",
    )
