"""JSON lines log: CONTRACTS 7 fields only, nothing from the forbidden list."""

from __future__ import annotations

import json
import logging
import logging.handlers
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.jobs import LIGHT, LOG_BACKUPS, LOG_FIELDS, LOG_MAX_BYTES, LocalJobContext, open_app_log
from app.schemas.job import Job, JobKind
from tests.jobs.support import Env, new_job, open_env

SECRET = "SECRET-prompt-text"
HOME_PATH = str(Path.home() / "private" / "clip.mp4")


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    opened = open_env(tmp_path)
    yield opened
    opened.close()


@pytest.fixture
def app_log(tmp_path: Path) -> Iterator[tuple[logging.Handler, Path]]:
    handler = open_app_log(tmp_path / "logdata")
    logger = logging.getLogger("app")
    level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield handler, tmp_path / "logdata" / "log" / "app.log"
    logger.removeHandler(handler)
    logger.setLevel(level)
    handler.close()


def _entries(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_log_writes_only_contract_fields(
    env: Env, app_log: tuple[logging.Handler, Path]
) -> None:
    handler, path = app_log

    def run_job(job: Job, ctx: LocalJobContext) -> dict[str, Any]:
        logging.getLogger("app.jobs").debug(
            "prompt %s at %s",
            SECRET,
            HOME_PATH,
            extra={"event": "debug_probe", "prompt": SECRET, "cookie": SECRET, "path": HOME_PATH},
        )
        raise RuntimeError(f"{SECRET} {HOME_PATH}")

    env.jobs.create(new_job(JobKind.chat))
    env.runner(run_job).run_once(LIGHT)
    try:
        raise ValueError(SECRET)
    except ValueError:
        logging.getLogger("app.jobs").exception(SECRET, extra={"event": "probe_exception"})
    handler.flush()

    text = path.read_text(encoding="utf-8")
    assert SECRET not in text and HOME_PATH not in text and "Traceback" not in text
    entries = _entries(path)
    assert {entry["event"] for entry in entries} >= {
        "job_started",
        "debug_probe",
        "job_failed",
        "probe_exception",
    }
    for entry in entries:
        assert set(entry) <= set(LOG_FIELDS)
        assert {"ts", "level", "event"} <= set(entry)
    failed = next(entry for entry in entries if entry["event"] == "job_failed")
    assert failed["error_code"] == "internal" and failed["kind"] == "chat"
    assert isinstance(failed["duration_ms"], int)


def test_log_rotates_at_5_mb_and_keeps_3_files(app_log: tuple[logging.Handler, Path]) -> None:
    handler, _ = app_log
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert (handler.maxBytes, handler.backupCount) == (LOG_MAX_BYTES, LOG_BACKUPS)
    assert LOG_MAX_BYTES == 5 * 1024 * 1024 and LOG_BACKUPS == 3
