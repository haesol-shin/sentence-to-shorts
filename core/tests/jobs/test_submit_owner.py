"""Submission gates and job input stay per owner and free of key material."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.bootstrap import LocalJobs
from app.ports import AppError
from app.schemas.job import JobKind
from app.storage.credentials import SqliteCredentialStore
from tests.jobs.support import open_env

ALLOWED_OWNER = "owner"
BLOCKED_OWNER = "u_0hzb7bexv28termtt2ypc6trzt"
SECRET = "synthetic-owner-secret-value"


class Projects:
    def get_project(self, project_id: str) -> None:
        raise AppError("not_found")


class Media:
    pass


class OwnerLlm:
    def __init__(self, allowed: str) -> None:
        self.allowed = allowed

    def auth_state(self, owner_id: str) -> str:
        return "ok" if owner_id == self.allowed else "missing"


class Vault:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get(self, owner_id: str, provider: str, credential_id: str) -> str | None:
        return self.values.get((owner_id, provider))

    def put(self, owner_id: str, provider: str, credential_id: str, secret: str) -> None:
        self.values[(owner_id, provider)] = secret

    def delete(self, owner_id: str, provider: str, credential_id: str) -> None:
        self.values.pop((owner_id, provider), None)


def _jobs(root: Path, llm: OwnerLlm) -> tuple[LocalJobs, object]:
    env = open_env(root)
    jobs = LocalJobs(
        store=env.jobs,
        inputs=env.inputs,
        projects=Projects(),  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
        media=Media(),  # type: ignore[arg-type]
        db=env.db,
        max_attempts={kind.value: 3 for kind in JobKind},
        wake=lambda: None,
    )
    return jobs, env


def test_submit_checks_llm_auth_per_owner(tmp_path: Path) -> None:
    jobs, env = _jobs(tmp_path, OwnerLlm(ALLOWED_OWNER))
    try:
        job = jobs.submit(
            JobKind.draft,
            owner_id=ALLOWED_OWNER,
            project_id=None,
            video_id=None,
            base_revision=None,
            request_digest="a" * 64,
            input={"message": "synthetic"},
            idempotency_key=None,
        ).job
        assert job.owner_id == ALLOWED_OWNER

        with pytest.raises(AppError) as refused:
            jobs.submit(
                JobKind.draft,
                owner_id=BLOCKED_OWNER,
                project_id=None,
                video_id=None,
                base_revision=None,
                request_digest="b" * 64,
                input={"message": "synthetic"},
                idempotency_key=None,
            )
        assert refused.value.code == "llm_auth_required"
        assert [item.owner_id for item in env.jobs.unfinished()] == [ALLOWED_OWNER]
    finally:
        env.close()


def test_job_input_never_contains_api_key(tmp_path: Path) -> None:
    jobs, env = _jobs(tmp_path, OwnerLlm(ALLOWED_OWNER))
    try:
        store = SqliteCredentialStore(env.db, Vault())
        store.put(ALLOWED_OWNER, "anthropic_api", SECRET, None)

        job = jobs.submit(
            JobKind.draft,
            owner_id=ALLOWED_OWNER,
            project_id=None,
            video_id=None,
            base_revision=None,
            request_digest="c" * 64,
            input={"message": "synthetic"},
            idempotency_key=None,
        ).job
        saved = env.inputs.load(job.id)
        assert saved == {"message": "synthetic"}
        assert SECRET not in json.dumps(saved)
        assert SECRET not in job.model_dump_json()
        with env.db.read() as conn:
            doc = conn.execute("SELECT doc FROM jobs WHERE id = ?", (job.id,)).fetchone()[0]
        assert SECRET not in doc
    finally:
        env.close()
