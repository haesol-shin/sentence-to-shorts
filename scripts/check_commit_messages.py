#!/usr/bin/env python3
"""Check commit messages from a Git range or a UTF-8 message file."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

TITLE = re.compile(r"[a-z][a-z0-9-]*\([A-Za-z0-9][A-Za-z0-9_./-]*\)!?: [!-~](?:[ -~]*[!-~])?")


def check_message(message: str) -> list[str]:
    problems = []
    lines = message.splitlines()
    if not lines or not TITLE.fullmatch(lines[0]):
        problems.append("title must be English type(scope): summary")
    if len(lines) < 3 or lines[1] != "":
        problems.append("title and required body must be separated by one blank line")
    for number, line in enumerate(lines[2:], 3):
        if not line.startswith("- ") or not line[2:].strip():
            problems.append(f"line {number}: expected one nonempty '- ' bullet")
        if len(line) > 72:
            problems.append(f"line {number}: exceeds 72 characters")
    return problems


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def check_range(revision_range: str) -> list[str]:
    commits = git("rev-list", "--reverse", revision_range, "--").splitlines()
    if not commits:
        return ["range contains no commits"]
    problems = []
    for commit in commits:
        message = git("show", "-s", "--format=format:%B", commit, "--")
        problems.extend(f"{commit}: {problem}" for problem in check_message(message))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--range", dest="revision_range", help="base..head (all PR commits)")
    source.add_argument("--message-file", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.message_file is not None:
            problems = check_message(args.message_file.read_text(encoding="utf-8"))
        else:
            problems = check_range(args.revision_range)
    except (OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        print(f"check_commit_messages: {exc}", file=sys.stderr)
        return 1
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print("check_commit_messages: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
