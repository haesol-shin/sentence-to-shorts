#!/usr/bin/env python3
"""Print the core test folders that cover the paths a pull request changed.

Reads one repository-relative path per line and prints one pytest target per
line, sorted. `scripts/test_selection.json` maps a source folder to the test
folders that cover it: each entry lists the tests that import the folder plus
the test folder of the same name, and the test folders are written relative to
`core/`, where pytest runs. A path the map does not list selects the full
suite, so a new shared module runs every test until someone maps it.

Usage:
    git diff --name-only origin/main...HEAD | python scripts/select_tests.py
    python scripts/select_tests.py --paths-file changed-paths.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

MAP_FILE = Path(__file__).with_name("test_selection.json")
FULL_SUITE = "tests"


@dataclass(frozen=True)
class TestMap:
    always: tuple[str, ...]
    folders: dict[str, tuple[str, ...]]
    no_core_tests: tuple[str, ...]

    @classmethod
    def load(cls, path: Path = MAP_FILE) -> TestMap:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            always=tuple(data["always"]),
            folders={key: tuple(value) for key, value in data["folders"].items()},
            no_core_tests=tuple(data["no_core_tests"]),
        )


def covers(path: str, entry: str) -> bool:
    """A trailing slash marks a directory entry; every other entry is one file."""
    if entry.endswith("/"):
        return path.startswith(entry)
    return path == entry


def select_tests(paths: list[str], mapping: TestMap) -> list[str]:
    selected = set(mapping.always)
    for path in paths:
        path = path.strip()
        if not path:
            continue
        if any(covers(path, entry) for entry in mapping.no_core_tests):
            continue
        keys = [key for key in mapping.folders if covers(path, key)]
        if not keys:
            return [FULL_SUITE]
        selected.update(mapping.folders[max(keys, key=len)])
    return sorted(selected)


def write_targets(targets: list[str], stream: object | None = None) -> None:
    """Write one target per line with a bare LF, even where the platform adds CR."""
    target_stream = sys.stdout if stream is None else stream
    text = "".join(f"{target}\n" for target in targets)
    buffer = getattr(target_stream, "buffer", None)
    if buffer is None:
        target_stream.write(text)
    else:
        buffer.write(text.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths-file", type=Path, help="file of changed paths; default stdin")
    args = parser.parse_args(argv)
    try:
        if args.paths_file is None:
            text = sys.stdin.read()
        else:
            text = args.paths_file.read_text(encoding="utf-8")
        mapping = TestMap.load()
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError) as exc:
        print(f"select_tests: {exc}", file=sys.stderr)
        return 1
    write_targets(select_tests(text.splitlines(), mapping))
    return 0


if __name__ == "__main__":
    sys.exit(main())
