"""Remote tag checks use real local Git repositories, never a public Release."""

from __future__ import annotations

import runpy
import subprocess
from pathlib import Path

import pytest

CHECK_TAG = runpy.run_path(
    str(Path(__file__).resolve().parents[3] / "packaging" / "release_tag.py")
)["check_tag"]


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str, str]:
    origin = tmp_path / "origin.git"
    git("init", "--bare", str(origin))
    checkout = tmp_path / "checkout"
    git("init", str(checkout))
    monkeypatch.chdir(checkout)
    git("config", "user.name", "Synthetic Author")
    git("config", "user.email", "author@example.invalid")
    git("config", "commit.gpgsign", "false")
    git("config", "tag.gpgsign", "false")
    git("remote", "add", "origin", str(origin))
    git(
        "commit", "--allow-empty", "-m", "test(fixtures): create first commit",
        "-m", "- Exercise tag checks without contacting a remote service",
    )
    first = git("rev-parse", "HEAD")
    git(
        "commit", "--allow-empty", "-m", "test(fixtures): create second commit",
        "-m", "- Exercise mismatched tag checks without a remote service",
    )
    second = git("rev-parse", "HEAD")
    git("push", "origin", "HEAD:refs/heads/main")
    return origin, first, second


@pytest.mark.parametrize("annotated", [False, True])
@pytest.mark.parametrize("matches", [False, True])
def test_release_tag_requires_the_remote_commit_to_match_the_build(
    remote: tuple[Path, str, str], annotated: bool, matches: bool,
) -> None:
    _origin, first, second = remote
    tag = "v1.0.0"
    git("tag", *(["-a", "-m", "synthetic release"] if annotated else []), tag, first)
    git("push", "origin", f"refs/tags/{tag}")
    if matches:
        CHECK_TAG(tag, first)
        CHECK_TAG(tag, first, create=True)
    else:
        with pytest.raises(ValueError, match="does not match"):
            CHECK_TAG(tag, second)
        with pytest.raises(ValueError, match="does not match"):
            CHECK_TAG(tag, second, create=True)
    assert git("rev-parse", f"refs/tags/{tag}^{{commit}}") == first


def test_release_tag_checks_again_after_the_build_even_if_the_local_tag_is_stale(
    remote: tuple[Path, str, str],
) -> None:
    origin, first, second = remote
    git("tag", "v1.0.0", first)
    git("push", "origin", "refs/tags/v1.0.0")
    CHECK_TAG("v1.0.0", first)
    git("--git-dir", str(origin), "update-ref", "refs/tags/v1.0.0", second)
    with pytest.raises(ValueError, match="does not match"):
        CHECK_TAG("v1.0.0", first, create=True)


def test_release_tag_only_creates_a_missing_tag_in_the_publishing_job(
    remote: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin, _first, sha = remote
    CHECK_TAG("v1.0.0", sha)
    assert git("ls-remote", "origin", "refs/tags/v1.0.0") == ""
    real_run = subprocess.run
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/project")

    def create_ref(command: list[str], **kwargs):  # type: ignore[no-untyped-def]
        if command[0] == "gh":
            assert command == [
                "gh", "api", "--method", "POST", "repos/example/project/git/refs",
                "-f", "ref=refs/tags/v1.0.0", "-f", f"sha={sha}",
            ]
            git("--git-dir", str(origin), "update-ref", "refs/tags/v1.0.0", sha)
            return subprocess.CompletedProcess(command, 0)
        return real_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", create_ref)
    CHECK_TAG("v1.0.0", sha, create=True)
    assert git("ls-remote", "origin", "refs/tags/v1.0.0").split()[0] == sha


def test_release_tag_does_not_treat_a_failed_remote_lookup_as_an_absent_tag(
    remote: tuple[Path, str, str], tmp_path: Path,
) -> None:
    _origin, _first, sha = remote
    git("remote", "set-url", "origin", str(tmp_path / "missing.git"))
    with pytest.raises(subprocess.CalledProcessError):
        CHECK_TAG("v1.0.0", sha, create=True)
