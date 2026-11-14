#!/usr/bin/env python3
"""Print one result as Markdown for the GitHub job summary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _number(value: float | int | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _mib(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value / (1024 * 1024):.0f}"


def render(result: dict) -> str:
    host = result.get("host", {})
    lines = [
        f"### {result.get('candidate', 'candidate')}",
        "",
        "| field | value |",
        "| --- | --- |",
        f"| status | {result.get('status', '-')} |",
        f"| os | {host.get('os', '-')} |",
        f"| cpu | {host.get('cpu', '-')} |",
        f"| ram | {_mib(host.get('ram_bytes'))} MiB |",
        f"| thread | {result.get('thread', '-')} |",
        f"| cold start | {_number(result.get('cold_start_ms'))} ms |",
        f"| first wav | {_number(result.get('first_wav_ms'))} ms |",
        f"| rtf | {_number(result.get('rtf'), 3)} |",
        f"| peak rss | {_mib(result.get('peak_rss_bytes'))} MiB |",
        f"| model bytes | {_mib(result.get('model_bytes'))} MiB |",
        f"| env bytes | {_mib(result.get('env_bytes'))} MiB |",
    ]
    failure = result.get("failure")
    if failure:
        message = str(failure.get("message", "")).splitlines()[:3]
        lines += ["", f"Failure at {failure.get('stage')}: {failure.get('code')}", ""]
        lines += [f"> {line}" for line in message]
    texts = result.get("texts", [])
    if texts:
        lines += ["", "| text | wav ms | rtf |", "| --- | --- | --- |"]
        for entry in texts:
            if entry.get("warmup"):
                continue
            lines.append(
                f"| {entry.get('id')} | {_number(entry.get('wav_ms'))} | {_number(entry.get('rtf'), 3)} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.result.is_file():
        print(f"no result at {args.result}")
        return 0
    print(render(json.loads(args.result.read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
