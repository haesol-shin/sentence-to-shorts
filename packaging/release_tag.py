"""Keep the remote Release tag on the verified build commit, including annotated tags."""

from __future__ import annotations

import argparse
import os
import re
import subprocess


def check_tag(tag: str, sha: str, *, create: bool = False) -> None:
    """Check the remote tag; only the publishing job may create a missing one.

    Re-read the remote immediately before publishing rather than trusting the checkout's
    tag cache. Never move an existing tag. A concurrent creation fails closed.
    """
    if not re.fullmatch(r"v[0-9][0-9A-Za-z._-]{0,60}", tag):
        raise ValueError("The tag name must look like v0.1.0.")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("The build SHA must be a full commit id.")
    ref = f"refs/tags/{tag}"
    found = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--refs", "origin", ref],
        check=False, capture_output=True, text=True,
    )
    if found.returncode == 2:
        if not create:
            return
        subprocess.run(
            [
                "gh", "api", "--method", "POST",
                f"repos/{os.environ['GITHUB_REPOSITORY']}/git/refs",
                "-f", f"ref={ref}", "-f", f"sha={sha}",
            ],
            check=True, capture_output=True, text=True,
        )
    else:
        found.check_returncode()
    subprocess.run(
        ["git", "fetch", "--quiet", "--no-tags", "origin", ref], check=True,
    )
    target = subprocess.run(
        ["git", "rev-parse", "FETCH_HEAD^{commit}"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if target != sha:
        raise ValueError("The remote Release tag does not match the verified build commit.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--create", action="store_true")
    args = parser.parse_args()
    check_tag(args.tag, args.sha, create=args.create)


if __name__ == "__main__":
    main()
