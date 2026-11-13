#!/usr/bin/env python3
"""Fail when a name from core/config/brand.yaml appears outside the allowlist.

core/config/brand.yaml is the single source of the service and repository
names. Every other file must read the name from it instead of repeating it.
The placeholder app_id value "app" is an ordinary word and is not checked.

Usage: python scripts/check_brand.py [--root DIR]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BRAND_FILE = "core/config/brand.yaml"
KEYS = ("display_name_ko", "display_name_en", "repository", "app_id")
PLACEHOLDER = "app"
# Paths that may contain the names. A trailing slash marks a directory prefix.
ALLOWLIST = (
    "LICENSE",
    ".git/",
    "README.md",
    "README.ko.md",
    BRAND_FILE,
)
# Used only when the root is not a git checkout.
SKIP_DIRS = {".git", ".local", ".venv", "node_modules", "__pycache__"}


def parse_brand(text: str) -> dict[str, str]:
    """Parse the flat `key: value` brand file without a YAML dependency."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_names(root: Path) -> tuple[list[str], list[str]]:
    """Return (names to look for, problems with the brand file itself)."""
    path = root / BRAND_FILE
    if not path.is_file():
        return [], [f"{BRAND_FILE}: file is missing"]
    values = parse_brand(path.read_text(encoding="utf-8"))
    problems = []
    names: list[str] = []
    for key in KEYS:
        value = values.get(key, "")
        if not value:
            problems.append(f"{BRAND_FILE}: {key} is missing or empty")
        elif value != PLACEHOLDER and value not in names:
            names.append(value)
    return names, problems


def is_allowed(rel: str) -> bool:
    return any(rel == a or (a.endswith("/") and rel.startswith(a)) for a in ALLOWLIST)


def list_files(root: Path) -> list[str]:
    """Tracked and untracked-but-not-ignored files; plain walk outside git."""
    if (root / ".git").exists():
        try:
            out = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                check=True,
                capture_output=True,
            ).stdout
            return sorted(p for p in out.decode("utf-8").split("\0") if p)
        except (OSError, subprocess.CalledProcessError):
            pass
    found = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if path.is_file() and not SKIP_DIRS.intersection(rel.parts):
            found.append(rel.as_posix())
    return sorted(found)


def check(root: Path) -> list[str]:
    names, problems = load_names(root)
    for rel in list_files(root):
        if is_allowed(rel):
            continue
        for name in names:
            if name in rel:
                problems.append(f"{rel}: path contains a brand name ({name!r})")
        path = root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for name in names:
                if name in line:
                    problems.append(f"{rel}:{number}: brand name {name!r} outside {BRAND_FILE}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    problems = check(args.root)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"check_brand: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print("check_brand: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
