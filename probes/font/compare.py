#!/usr/bin/env python3
"""Compare the per-platform probe results and record where rendering differs.

Each platform leg writes its own result.json. This step pairs the runs, checks
the pixel digest of every font and case, and leaves a diff image for the areas
that differ. A difference is a result, not a harness error: it is recorded and
the step still succeeds. Only an unreadable result set fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from PIL import Image, ImageChops

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Run:
    label: str
    result: dict
    root: Path

    @property
    def run_info(self) -> dict:
        return self.result.get("run", {})

    def png_path(self, relative) -> Path | None:
        return (self.root / relative) if relative else None


def load_runs(root: Path) -> list[Run]:
    runs = []
    for path in sorted(root.rglob("result.json")):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit(f"compare: cannot read {path}: {error}")
        runs.append(Run(label=run_label(result), result=result, root=path.parent))
    return runs


def run_label(result: dict) -> str:
    run = result.get("run", {})
    return str(run.get("runner") or run.get("platform") or run.get("os") or "unknown")


def cause_candidates(
    run_a: dict, run_b: dict, font_a: dict, font_b: dict, result_a: dict, result_b: dict
) -> list[str]:
    causes = []
    if font_a.get("file", {}).get("sha256") != font_b.get("file", {}).get("sha256"):
        causes.append("the font file digest differs between the runs")
    if run_a.get("freetype") != run_b.get("freetype"):
        causes.append(f"FreeType differs: {run_a.get('freetype')} vs {run_b.get('freetype')}")
    if run_a.get("layout_engine") != run_b.get("layout_engine"):
        causes.append(f"layout engine differs: {run_a.get('layout_engine')} vs {run_b.get('layout_engine')}")
    if run_a.get("raqm") != run_b.get("raqm"):
        causes.append(f"raqm differs: {run_a.get('raqm')} vs {run_b.get('raqm')}")
    if result_a.get("layout") != result_b.get("layout"):
        causes.append("the caption layout differs between the runs")
    if not causes:
        causes.append("identical inputs and versions, so the platform FreeType build or hinting differs")
    return causes


def compare_pair(
    run_a: Run, run_b: Run, font_id: str, case_id: str, font_a: dict, font_b: dict, record_a: dict, record_b: dict, diff_writer
) -> dict:
    pixels_equal = record_a.get("pixels_sha256") == record_b.get("pixels_sha256")
    png_equal = record_a.get("png_sha256") == record_b.get("png_sha256")
    entry = {
        "font": font_id,
        "case": case_id,
        "runs": [run_a.label, run_b.label],
        "status": "equal" if pixels_equal else "different",
        "pixels_equal": pixels_equal,
        "png_equal": png_equal,
        "font_file_equal": font_a.get("file", {}).get("sha256") == font_b.get("file", {}).get("sha256"),
    }
    if not pixels_equal:
        entry["diff"] = diff_writer(font_id, case_id, run_a.png_path(record_a.get("png")), run_b.png_path(record_b.get("png")))
        entry["cause_candidates"] = cause_candidates(
            run_a.run_info, run_b.run_info, font_a, font_b, run_a.result, run_b.result
        )
    elif not png_equal:
        entry["cause_candidates"] = ["pixels match, so only the PNG encoder output differs"]
    return entry


def build_comparison(runs: list[Run], diff_writer) -> dict:
    index: dict[tuple[str, str], list[tuple[Run, dict, dict]]] = {}
    for run in runs:
        for font in run.result.get("fonts", []):
            for case_id, record in font.get("render", {}).items():
                index.setdefault((font.get("font_id", ""), case_id), []).append((run, font, record))
    pairs = []
    pending = []
    for font_id, case_id in sorted(index):
        entries = index[(font_id, case_id)]
        if len(entries) < 2:
            pending.append({"font": font_id, "case": case_id, "run": entries[0][0].label})
            continue
        for (run_a, font_a, record_a), (run_b, font_b, record_b) in combinations(entries, 2):
            pairs.append(compare_pair(run_a, run_b, font_id, case_id, font_a, font_b, record_a, record_b, diff_writer))
    return {
        "schema_version": SCHEMA_VERSION,
        "probe": "font-caption",
        "runs": [
            {"label": run.label, "run": run.run_info, "layout": run.result.get("layout", {})} for run in runs
        ],
        "pairs": pairs,
        "pending": pending,
        "summary": {
            "run_count": len(runs),
            "equal": sum(1 for pair in pairs if pair["status"] == "equal"),
            "different": sum(1 for pair in pairs if pair["status"] == "different"),
            "pending": len(pending),
        },
    }


def summary_markdown(comparison: dict) -> str:
    summary = comparison["summary"]
    labels = ", ".join(run["label"] for run in comparison["runs"]) or "none"
    lines = [
        f"## Font digest comparison: {labels}",
        "",
        (
            f"{summary['run_count']} run(s): {summary['equal']} same, "
            f"{summary['different']} different, {summary['pending']} pending."
        ),
        "",
        "| Font | Cases | Same | Different | Pending |",
        "| --- | --- | --- | --- | --- |",
    ]
    per_font: dict[str, dict[str, int]] = {}
    for pair in comparison["pairs"]:
        counts = per_font.setdefault(pair["font"], {"total": 0, "same": 0, "different": 0, "pending": 0})
        counts["total"] += 1
        counts["same" if pair["status"] == "equal" else "different"] += 1
    for item in comparison["pending"]:
        counts = per_font.setdefault(item["font"], {"total": 0, "same": 0, "different": 0, "pending": 0})
        counts["total"] += 1
        counts["pending"] += 1
    for font_id in sorted(per_font):
        counts = per_font[font_id]
        lines.append(
            f"| {font_id} | {counts['total']} | {counts['same']} | {counts['different']} | {counts['pending']} |"
        )
    differences = [pair for pair in comparison["pairs"] if pair["status"] == "different"]
    if differences:
        lines += ["", "Differences:"]
        for pair in differences:
            difference = pair.get("diff", {})
            image = difference.get("diff_png") or difference.get("note") or "no image"
            lines.append(f"- {pair['font']}/{pair['case']}: pixels differ, {image}")
        causes = sorted({cause for pair in differences for cause in pair.get("cause_candidates", [])})
        if causes:
            lines += ["", "Cause candidates:"]
            lines += [f"- {cause}" for cause in causes]
    if comparison["pending"]:
        cases = sorted({item["case"] for item in comparison["pending"]})
        lines += [
            "",
            f"Pending, one run only: {len(comparison['pending'])} case(s) ({', '.join(cases)}).",
        ]
    lines.append("")
    return "\n".join(lines)


def write_diff(out_dir: Path, font_id: str, case_id: str, png_a, png_b) -> dict:
    """Save a crop of both renders and the amplified difference."""
    path_a = Path(png_a) if png_a else None
    path_b = Path(png_b) if png_b else None
    if not path_a or not path_b or not path_a.is_file() or not path_b.is_file():
        return {"diff_png": None, "note": "source PNG missing"}
    left = Image.open(path_a).convert("RGB")
    right = Image.open(path_b).convert("RGB")
    if left.size != right.size:
        return {"diff_png": None, "note": f"image size differs: {left.size} vs {right.size}"}
    difference = ImageChops.difference(left, right)
    bbox = difference.getbbox()
    if bbox is None:
        return {"diff_png": None, "note": "no differing pixel"}
    mask = difference.convert("L")
    padding = 24
    x0, y0, x1, y1 = bbox
    crop = (max(0, x0 - padding), max(0, y0 - padding), min(left.width, x1 + padding), min(left.height, y1 + padding))
    left_crop = left.crop(crop)
    right_crop = right.crop(crop)
    amplified = mask.crop(crop).point(lambda value: min(255, value * 8)).convert("RGB")
    width, height = left_crop.size
    separator = 6
    canvas = Image.new("RGB", (width, height * 3 + separator * 2), (96, 96, 96))
    canvas.paste(left_crop, (0, 0))
    canvas.paste(right_crop, (0, height + separator))
    canvas.paste(amplified, (0, 2 * (height + separator)))
    target = out_dir / "diff" / f"{font_id}-{case_id}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, format="PNG")
    return {
        "diff_png": target.relative_to(out_dir).as_posix(),
        "diff_bbox": [x0, y0, x1 - x0, y1 - y0],
        "diff_pixels": sum(mask.histogram()[1:]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, required=True, help="directory holding one result.json per run")
    parser.add_argument("--out-dir", type=Path, required=True, help="where digest-compare.json and diff images go")
    args = parser.parse_args(argv)
    runs = load_runs(args.results)
    if not runs:
        print(f"compare: no result.json under {args.results}", file=sys.stderr)
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)

    def diff_writer(font_id: str, case_id: str, png_a, png_b) -> dict:
        return write_diff(args.out_dir, font_id, case_id, png_a, png_b)

    comparison = build_comparison(runs, diff_writer)
    (args.out_dir / "digest-compare.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown = summary_markdown(comparison)
    (args.out_dir / "compare-summary.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
