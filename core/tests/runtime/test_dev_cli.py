"""Official CLI check of the developer distribution: presence, version, login."""

from __future__ import annotations

from collections.abc import Sequence

from app.runtime.dev_cli import GUIDE_URL, check_claude_cli, parse_version

MINIMUM = (2, 1, 325)


def runner(answers: dict[str, tuple[int | None, str]], calls: list[list[str]] | None = None):  # type: ignore[no-untyped-def]
    def run(argv: Sequence[str]) -> tuple[int | None, str]:
        if calls is not None:
            calls.append(list(argv))
        return answers[" ".join(argv[1:])]

    return run


def test_dev_cli_reports_a_missing_cli_with_the_official_guide() -> None:
    status = check_claude_cli(MINIMUM, which=lambda _name: None, run=runner({}))
    assert status.state == "missing" and GUIDE_URL in status.message


def test_dev_cli_reports_an_old_version_before_asking_about_login() -> None:
    calls: list[list[str]] = []
    status = check_claude_cli(
        MINIMUM,
        which=lambda _name: "/bin/claude",
        run=runner({"--version": (0, "2.1.100 (Claude Code)\n")}, calls),
    )
    assert status.state == "too_old" and status.version == "2.1.100"
    assert calls == [["/bin/claude", "--version"]]


def test_dev_cli_reports_a_cli_that_cannot_tell_its_version() -> None:
    status = check_claude_cli(
        MINIMUM, which=lambda _name: "/bin/claude", run=runner({"--version": (None, "")})
    )
    assert status.state == "unknown"


def test_dev_cli_reports_a_cli_that_is_not_signed_in() -> None:
    status = check_claude_cli(
        MINIMUM,
        which=lambda _name: "/bin/claude",
        run=runner({"--version": (0, "2.2.0"), "auth status": (1, "{}")}),
    )
    assert status.state == "not_logged_in" and "auth login" in status.message


def test_dev_cli_reports_a_ready_cli_and_never_prints_account_details() -> None:
    status = check_claude_cli(
        MINIMUM,
        which=lambda _name: "/bin/claude",
        run=runner({"--version": (0, "2.2.0"), "auth status": (0, '{"email": "a@b.invalid"}')}),
    )
    assert status.state == "ok" and status.version == "2.2.0"
    assert "invalid" not in status.message


def test_dev_cli_version_parser_reads_the_first_dotted_number() -> None:
    assert parse_version("claude 2.1.325 (build 9)") == (2, 1, 325)
    assert parse_version("no digits") is None
