#!/usr/bin/env python3
"""Resolve candidate text-to-speech requirements together with WhisperX.

One resolution per candidate and platform, with no install. A candidate
requirements file that pins a torch build outside the aligner range fails here
before any wheel is downloaded, which is the answer the probe records.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CANDIDATES = (
    "qwen3-tts-0.6b",
    "qwen3-tts-1.7b",
    "moss-tts-nano-100m",
    "chatterbox-multilingual-v3",
)
PIN_PATTERN = re.compile(r"^([a-zA-Z0-9_.-]+)==([^\s]+)$")
TRACKED = ("torch", "torchaudio", "torchcodec", "huggingface-hub", "tokenizers", "onnxruntime", "transformers")


def _keep_reason(stderr: str, paths: list[Path]) -> str:
    """Keep the conflict text without machine paths."""
    text = stderr
    marker = text.find("No solution found")
    if marker >= 0:
        text = text[marker:]
    for path in paths:
        text = text.replace(str(path), "<path>")
    text = re.sub(r"(?<![\w.:/])/(?:[^\s'\"]+)", "<path>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:800]


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = PIN_PATTERN.match(line.strip())
        if match and match.group(1).lower() in TRACKED:
            pins[match.group(1).lower()] = match.group(2)
    return pins


def _relaxed_input(candidate: str, repo: Path, target: Path) -> Path:
    """Candidate input without the shared hub and tokenizer pins."""
    source = repo / "probes" / "tts" / candidate / "requirements.in"
    kept = [
        line
        for line in source.read_text(encoding="utf-8").splitlines()
        if not line.startswith(("huggingface-hub", "tokenizers"))
    ]
    target.write_text("\n".join(kept) + "\nwhisperx==3.8.6\n", encoding="utf-8")
    return target


def _compile(uv: str, python: str, platform: str, input_path: Path, output_path: Path, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            uv,
            "pip",
            "compile",
            "--quiet",
            "--no-header",
            "--python",
            python,
            "--python-platform",
            platform,
            "--output-file",
            str(output_path),
            str(input_path),
        ],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=Path(__file__).resolve().parents[2], type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--platform", action="append", help="uv platform name; repeatable")
    parser.add_argument("--python", default="3.11")
    parser.add_argument("--uv", default="uv")
    args = parser.parse_args(argv)
    platforms = args.platform or ["x86_64-manylinux_2_28"]
    scenarios = [("whisperx", None, None)]
    for candidate in CANDIDATES:
        scenarios.append((candidate, candidate, "published"))
        scenarios.append((candidate, candidate, "shared_pins_relaxed"))
    records = []
    with tempfile.TemporaryDirectory(prefix="align-install-") as raw_dir:
        work = Path(raw_dir)
        for platform in platforms:
            for name, candidate, variant in scenarios:
                if candidate is None:
                    input_path = work / "whisperx.in"
                    input_path.write_text("whisperx==3.8.6\n", encoding="utf-8")
                elif variant == "published":
                    input_path = work / f"{candidate}.in"
                    input_path.write_text(
                        f"-r {args.repo / 'probes' / 'tts' / candidate / 'requirements.txt'}\nwhisperx==3.8.6\n",
                        encoding="utf-8",
                    )
                else:
                    input_path = _relaxed_input(candidate, args.repo, work / f"{candidate}-relaxed.in")
                output_path = work / f"{name}-{variant}-{platform}.txt"
                try:
                    completed = _compile(args.uv, args.python, platform, input_path, output_path, args.repo)
                except subprocess.TimeoutExpired:
                    records.append(
                        {
                            "scenario": name,
                            "variant": variant or "aligner",
                            "platform": platform,
                            "status": "timeout",
                            "pins": {},
                            "reason": "resolution exceeded 300 s",
                        }
                    )
                    continue
                if completed.returncode == 0:
                    records.append(
                        {
                            "scenario": name,
                            "variant": variant or "aligner",
                            "platform": platform,
                            "status": "resolved",
                            "pins": _pins(output_path),
                            "reason": "",
                        }
                    )
                else:
                    records.append(
                        {
                            "scenario": name,
                            "variant": variant or "aligner",
                            "platform": platform,
                            "status": "failed",
                            "pins": {},
                            "reason": _keep_reason(completed.stderr, [work, args.repo]),
                        }
                    )
    payload = {
        "schema": 1,
        "python": args.python,
        "platforms": platforms,
        "records": records,
        "summary": {
            platform: {
                record["scenario"]: record["status"]
                for record in records
                if record["platform"] == platform and record["variant"] == "published"
            }
            for platform in platforms
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failed = [record for record in records if record["status"] != "resolved"]
    print(json.dumps({"records": len(records), "failed": len(failed)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
