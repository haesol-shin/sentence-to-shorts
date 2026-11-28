#!/usr/bin/env python3
"""Run the checks that a pull request must pass, before review.

The checkers and their arguments are the ones in `.github/workflows/ci.yml`, so
a failure here is a failure in CI. The test targets come from
`scripts/select_tests.py`, the map that also drives PR CI; when the map selects
the whole `tests` folder the suite stays in CI, because the full suite is CI's
job. Vitest runs only what the changed paths reach, and a failed cheap check
skips the heavy steps; see `vitest_command` and `run_checks`. Commit first:
the changed paths and the commit messages are read from the commit range.

Usage:
    python scripts/check_fast.py
    python scripts/check_fast.py --base origin/main
    python scripts/check_fast.py --title-file title.txt --squash-file commit.txt
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
FRONTEND = ROOT / "frontend"
DEFAULT_BASE = "origin/main"
FULL_SUITE = "tests"
SELECTOR = "scripts/select_tests.py"
COMMIT_CHECK = "scripts/check_commit_messages.py"
# The paths `scripts/export_schemas.py` and `npm run gen:api` write. The
# committed copy is what CI compares, so a local diff of other files is not a
# failure.
GENERATED_PATHS = ("schemas/", "core/openapi.json", "frontend/src/shared/api/generated/")
# CI installs markdown-it-py in an isolated environment; `uv run --with` is the
# local equivalent written in CONTRIBUTING.md.
MARKDOWN_ENV = ("uv", "run", "--with", "markdown-it-py==3.0.0", "python")
PYTEST_MARKERS = ("-q", "-rfE", "-m", "not sandbox and not models and not realllm")
# Vitest runs on at most this many workers in the local check; CI keeps vitest's default.
VITEST_WORKERS = "2"
# Source kinds `vitest related` follows through the import graph. A changed file of
# any other kind (a snapshot, a fixture read from disk) may feed a test the graph
# cannot reach, so it runs the full suite.
RELATED_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".json", ".css")
# A changed file whose name says it prepares every test can break any of them.
SETUP_MARKER = "setup"

Runner = Callable[[Sequence[str], Path], tuple[int, str]]


def run(argv: Sequence[str], cwd: Path = ROOT) -> tuple[int, str]:
    """Run one command from cwd and return its exit code with stdout and stderr."""
    command = [str(part) for part in argv]
    print(f"$ {' '.join(command)}")
    try:
        done = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return 127, f"{command[0]}: {exc}"
    return done.returncode, done.stdout + done.stderr


def squash_message(title: str, body: str) -> str:
    """Join the PR title and the body-only squash message the way a merge writes it."""
    return f"{title.strip()}\n\n{body.strip()}\n"


class Checks:
    """Print each check with its output and remember the names that failed."""

    def __init__(self, runner: Runner) -> None:
        self.runner = runner
        self.failed: list[str] = []

    def run(self, name: str, argv: Sequence[str], cwd: Path = ROOT) -> bool:
        """Run one check and return whether it passed."""
        print(f"== {name}")
        code, output = self.runner(argv, cwd)
        if output.strip():
            print(output.rstrip())
        if code:
            self.failed.append(name)
            print(f"== {name}: failed (exit {code})")
            return False
        print(f"== {name}: ok")
        return True

    def fail(self, name: str, reason: object) -> None:
        """Record a check that failed before a command could start."""
        self.failed.append(name)
        print(f"== {name}: failed: {reason}")

    def skip(self, name: str, reason: str) -> None:
        """Print a check that is left to CI."""
        print(f"== {name}: {reason}")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base",
        default=DEFAULT_BASE,
        help=f"ref to compare with, through git merge-base (default {DEFAULT_BASE})",
    )
    parser.add_argument("--title-file", type=Path, help="PR title to check")
    parser.add_argument(
        "--squash-file",
        type=Path,
        help="body-only squash message to check together with the title",
    )
    return parser.parse_args(argv)


def vitest_command(paths: list[str]) -> tuple[list[str] | None, str]:
    """Pick the vitest run for the changed paths: none, related files, or all."""
    prefix = f"{FRONTEND.name}/"
    changed = [path for path in paths if path.startswith(prefix)]
    if not changed:
        return None, "CI only (no frontend path changed)"
    env = ["env", f"VITEST_MAX_WORKERS={VITEST_WORKERS}"]
    related = []
    for path in changed:
        inside = path[len(prefix) :]
        followed = inside.startswith(("src/", "tests/")) and inside.endswith(
            RELATED_SUFFIXES
        )
        if (
            not followed
            or SETUP_MARKER in inside.rsplit("/", 1)[-1].lower()
            or not (ROOT / path).is_file()
        ):
            reason = f"full suite ({path} is not followed by related mode)"
            return [*env, "npm", "test"], reason
        related.append(inside)
    command = ["npm", "exec", "--offline", "--yes=false", "--", "vitest", "related"]
    return (
        [*env, *command, "--run", "--passWithNoTests", *related],
        f"related to {len(related)} changed file(s)",
    )


def changed_paths(ref: str, runner: Runner) -> tuple[list[str], str, str | None]:
    """Return the paths the branch changed since ref, its merge base, and an error."""
    code, output = runner(["git", "merge-base", "HEAD", ref], ROOT)
    if code or not output.strip():
        print(output.rstrip())
        return [], "", f"cannot resolve --base {ref}"
    base = output.strip()
    print(f"base {base}")
    code, output = runner(
        ["git", "diff", "--no-renames", "--name-only", "-z", f"{base}...HEAD"], ROOT
    )
    if code:
        print(output.rstrip())
        return [], base, "cannot list the changed paths"
    paths = [path for path in output.split("\0") if path]
    print(f"changed paths: {len(paths)}")
    return paths, base, None


def run_checks(
    checks: Checks,
    paths: list[str],
    base_line: str,
    args: argparse.Namespace,
    workspace: Path,
) -> None:
    """Run the fixed checks, the commit text checks, and the selected tests."""
    checks.run("brand", [sys.executable, "scripts/check_brand.py"])
    checks.run("public documents", [*MARKDOWN_ENV, "scripts/check_public_docs.py"])
    checks.run(
        "check script tests",
        [*MARKDOWN_ENV, "-m", "unittest", "discover", "-s", "scripts/tests", "-v"],
    )
    checks.run(
        "commit messages",
        [sys.executable, COMMIT_CHECK, "--range", base_line],
    )

    title = None
    if args.title_file is not None:
        try:
            title = args.title_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            checks.fail("pr title", exc)
        else:
            checks.run(
                "pr title",
                [sys.executable, COMMIT_CHECK, "--pr-title", title],
            )
    if args.squash_file is not None:
        if title is None:
            checks.fail("squash message", "--squash-file needs a readable --title-file")
        else:
            try:
                body = args.squash_file.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                checks.fail("squash message", exc)
            else:
                message_file = workspace / "squash-message.txt"
                message_file.write_text(squash_message(title, body), encoding="utf-8")
                checks.run(
                    "squash message",
                    [sys.executable, COMMIT_CHECK, "--message-file", str(message_file)],
                )

    checks.run("ruff", ["poetry", "run", "ruff", "check", "."], CORE)
    checks.run("import contracts", ["poetry", "run", "lint-imports"], CORE)
    checks.run("eslint", ["npm", "run", "lint"], FRONTEND)
    checks.run("typescript", ["npm", "run", "typecheck"], FRONTEND)
    if checks.failed:
        reason = f"skipped after a failed check ({', '.join(checks.failed)})"
        for name in (
            "vitest", "generated schemas", "generated api types", "generated files", "tests"
        ):
            checks.skip(name, reason)
        return

    vitest_argv, vitest_reason = vitest_command(paths)
    if vitest_argv is None:
        checks.skip("vitest", vitest_reason)
    else:
        print(f"== vitest: {vitest_reason}")
        checks.run("vitest", vitest_argv, FRONTEND)

    if checks.run(
        "generated schemas",
        ["poetry", "run", "python", "../scripts/export_schemas.py"],
        CORE,
    ) and checks.run("generated api types", ["npm", "run", "gen:api"], FRONTEND):
        checks.run(
            "generated files",
            ["git", "diff", "--exit-code", "--", *GENERATED_PATHS],
        )

    paths_file = workspace / "changed-paths.txt"
    paths_file.write_text("".join(f"{path}\n" for path in paths), encoding="utf-8")
    code, output = checks.runner(
        [sys.executable, SELECTOR, "--paths-file", str(paths_file)], ROOT
    )
    if code:
        print(output.rstrip())
        checks.fail("tests", f"{SELECTOR} failed")
        return
    targets = output.replace("\r", "").split()
    if not targets:
        checks.fail("tests", f"{SELECTOR} selected no target")
    elif targets == [FULL_SUITE]:
        checks.skip("tests", "CI only")
    else:
        checks.run(
            "tests",
            ["poetry", "run", "pytest", *targets, *PYTEST_MARKERS],
            CORE,
        )


def main(argv: list[str] | None = None, runner: Runner = run) -> int:
    args = parse_args(argv)
    checks = Checks(runner)
    paths, base, error = changed_paths(args.base, runner)
    if error is not None:
        print(f"fast check: failed: {error}")
        return 1
    with tempfile.TemporaryDirectory(prefix="fast-check-") as tmp:
        run_checks(checks, paths, f"{base}..HEAD", args, Path(tmp))
    if checks.failed:
        print(f"fast check: failed: {', '.join(checks.failed)}")
        return 1
    print("fast check: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
