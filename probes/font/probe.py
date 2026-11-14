#!/usr/bin/env python3
"""Measure the caption font candidates before the product picks one.

The probe answers three questions per candidate: which code points the font
has no glyph for, how the caption line breaks at the real glyph width against
the character rule, and whether the same input draws the same pixels on every
platform. A failing measurement is a result: it goes into result.json as a
finding and the run still succeeds. A failure to fetch or load an input is a
harness error and fails the run.

Probe-only code. It is not imported by the product and its dependencies are
not product dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import PIL
import fontTools
import regex
from fontTools.ttLib import TTLibError
from PIL import ImageFont, features

import candidates
import coverage
import render
import texts
import wrap


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, help="where result.json, summary.md and PNGs go")
    parser.add_argument("--work-dir", type=Path, help="where downloads and unpacked fonts go")
    parser.add_argument("--font-size", type=int, default=64, help="caption font size in pixels")
    parser.add_argument("--line-height", type=int, default=80, help="caption line height in pixels")
    parser.add_argument("--skip-png", action="store_true", help="record digests without writing PNG files")
    parser.add_argument("--keep-downloads", action="store_true", help="keep a temporary work directory")
    return parser.parse_args(argv)


def environment() -> dict:
    has_raqm = bool(features.check("raqm"))
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "platform": platform.platform(terse=True),
        "runner": os.environ.get("PROBE_RUNNER_LABEL") or None,
        "python": platform.python_version(),
        "pillow": PIL.__version__,
        "fonttools": fontTools.version,
        "regex": regex.__version__,
        "freetype": features.version("freetype2") if features.check("freetype2") else None,
        "raqm": features.version("raqm") if has_raqm else None,
        "layout_engine": "raqm" if has_raqm else "basic",
    }


def max_font_size(font_path: Path, text: str, box_width: int, low: int = 6, high: int = 256) -> int:
    """Largest integer size at which the text still fits the box."""
    best = 0
    while low <= high:
        middle = (low + high) // 2
        if ImageFont.truetype(str(font_path), middle).getlength(text) <= box_width:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    return best


def max_clusters(font: ImageFont.FreeTypeFont, char: str, box_width: int, ceiling: int = 240) -> int:
    """How many copies of one character fit on one line."""
    count = 0
    while count < ceiling and font.getlength(char * (count + 1)) <= box_width:
        count += 1
    return count


def widest_latin(font: ImageFont.FreeTypeFont, samples: str = "MWmw0") -> tuple[str, float]:
    """The widest common Latin character and its width at the caption size."""
    char = max(samples, key=lambda sample: font.getlength(sample))
    return char, font.getlength(char)


def font_metrics(font: ImageFont.FreeTypeFont, font_path: Path, info: coverage.FontInfo, layout: render.Layout) -> dict:
    ascent, descent = font.getmetrics()
    widest, _ = widest_latin(font)
    return {
        "units_per_em": info.units_per_em,
        "cmap_glyphs": info.glyph_count,
        "ascent_px": ascent,
        "descent_px": descent,
        "korean_advance_px": round(font.getlength("가"), 2),
        "latin_advance_px": round(font.getlength("a"), 2),
        "latin_widest_char": widest,
        "max_korean_clusters_per_line": max_clusters(font, "가", layout.box_width),
        "max_latin_clusters_per_line": max_clusters(font, widest, layout.box_width),
        "korean_rule_width_px": round(font.getlength("가" * texts.LIMITS["ko"]), 2),
        "latin_rule_worst_width_px": round(font.getlength(widest * texts.LIMITS["en"]), 2),
        "max_font_size_korean_14": max_font_size(font_path, "가" * texts.LIMITS["ko"], layout.box_width),
        "max_font_size_latin_28": max_font_size(font_path, widest * texts.LIMITS["en"], layout.box_width),
    }


def render_case(font: ImageFont.FreeTypeFont, lines: list[str], layout: render.Layout) -> dict:
    return render.digests(render.draw(font, lines, layout))


def collect_findings(
    font_id: str,
    coverage_cases: dict,
    wrap_cases: dict,
    alternate_missing: list[dict],
    metrics: dict,
    layout: render.Layout,
    render_cases: dict,
) -> list[dict]:
    findings = []
    for case in texts.CASES:
        missing = coverage_cases[case.case_id]["missing"]
        if missing:
            findings.append(
                {
                    "font": font_id,
                    "case": case.case_id,
                    "kind": "missing_glyph",
                    "detail": f"{len(missing)} code point(s) absent: " + ", ".join(item["codepoint"] for item in missing),
                }
            )
        measured = wrap_cases[case.case_id]
        if measured["rule_overflow"]:
            widest = max(measured["rule_line_width_px"])
            findings.append(
                {
                    "font": font_id,
                    "case": case.case_id,
                    "kind": "character_rule_overflow",
                    "detail": f"a line of the character rule needs {widest} px",
                }
            )
        if not measured["fits"]:
            findings.append(
                {
                    "font": font_id,
                    "case": case.case_id,
                    "kind": "caption_needs_more_lines",
                    "detail": f"{measured['pixel_line_count']} lines by pixel width",
                }
            )
    if coverage_cases["jamo"]["missing"] and not alternate_missing:
        alternate = render_cases.get("jamo", {}).get("alternate", {})
        if alternate.get("differs_from_case"):
            shaped = "the rendered pixels differ from the composed form"
        else:
            shaped = "the shaping engine drew it as the composed form here"
        findings.append(
            {
                "font": font_id,
                "case": "jamo",
                "kind": "nfc_normalization_required",
                "detail": f"cmap has no jamo glyph; {shaped}",
            }
        )
    if (
        metrics["korean_rule_width_px"] > layout.box_width
        or metrics["latin_rule_worst_width_px"] > layout.box_width
    ):
        findings.append(
            {
                "font": font_id,
                "case": "worst_case",
                "kind": "character_rule_headroom",
                "detail": (
                    f"14 Korean characters need {metrics['korean_rule_width_px']} px, "
                    f"28 copies of {metrics['latin_widest_char']!r} need "
                    f"{metrics['latin_rule_worst_width_px']} px"
                ),
            }
        )
    return findings


def probe_font(
    candidate: candidates.Candidate,
    work_dir: Path,
    layout: render.Layout,
    out_dir: Path,
    skip_png: bool,
) -> tuple[dict, list[dict]]:
    unpacked = candidates.unpack(candidate, work_dir / "downloads", work_dir / "fonts")
    font_path: Path = unpacked["font_path"]
    info = coverage.load(font_path)
    font = ImageFont.truetype(str(font_path), layout.font_size)

    coverage_cases = {}
    wrap_cases = {}
    for case in texts.CASES:
        coverage_cases[case.case_id] = {
            "clusters": len(texts.split_clusters(case.text)),
            "missing": coverage.missing_glyphs(info.cmap, case.text),
        }
        wrap_cases[case.case_id] = wrap.compare(case, font.getlength, layout.box_width, layout.max_lines)

    render_cases = {}
    for case in texts.CASES:
        image = render.draw(font, wrap_cases[case.case_id]["pixel_lines"], layout)
        render_record = render.digests(image)
        if not skip_png:
            target = out_dir / "png" / candidate.font_id / f"{case.case_id}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(render.encode(image))
            render_record["png"] = target.relative_to(out_dir).as_posix()
        if case.alternate:
            alternate_lines = wrap.as_text(
                wrap.pixel_lines(texts.split_clusters(case.alternate), layout.box_width, font.getlength)
            )
            alternate = render_case(font, alternate_lines, layout)
            render_record["alternate"] = {
                "text": case.alternate,
                "missing": coverage.missing_glyphs(info.cmap, case.alternate),
                **alternate,
                "differs_from_case": alternate["pixels_sha256"] != render_record["pixels_sha256"],
            }
        if case.typewriter:
            clusters = texts.split_clusters(case.text)
            prefixes = []
            for index in range(1, len(clusters) + 1):
                prefix = "".join(clusters[:index])
                prefix_lines = wrap.as_text(
                    wrap.pixel_lines(texts.split_clusters(prefix), layout.box_width, font.getlength)
                )
                prefixes.append(render_case(font, prefix_lines, layout)["pixels_sha256"])
            render_record["typewriter_prefix_pixels_sha256"] = prefixes
        render_cases[case.case_id] = render_record

    jamo = texts.CASE_BY_ID["jamo"]
    alternate_missing = coverage.missing_glyphs(info.cmap, jamo.alternate or "")
    metrics = font_metrics(font, font_path, info, layout)
    findings = collect_findings(
        candidate.font_id, coverage_cases, wrap_cases, alternate_missing, metrics, layout, render_cases
    )
    verdict = {
        "missing_glyph_cases": [case.case_id for case in texts.CASES if coverage_cases[case.case_id]["missing"]],
        "korean_rule_max_width_px": max(
            (
                width
                for case in texts.CASES
                if case.rule == "ko"
                for width in wrap_cases[case.case_id]["rule_line_width_px"]
            ),
            default=0.0,
        ),
        "english_rule_max_width_px": max(
            (
                width
                for case in texts.CASES
                if case.rule == "en"
                for width in wrap_cases[case.case_id]["rule_line_width_px"]
            ),
            default=0.0,
        ),
        "korean_rule_worst_width_px": metrics["korean_rule_width_px"],
        "latin_rule_worst_width_px": metrics["latin_rule_worst_width_px"],
        "sampled_rule_overflow_cases": [
            case.case_id for case in texts.CASES if wrap_cases[case.case_id]["rule_overflow"]
        ],
        "caption_fits_two_lines": all(wrap_cases[case.case_id]["fits"] for case in texts.CASES),
    }
    verdict["korean_rule_fits"] = verdict["korean_rule_max_width_px"] <= layout.box_width
    verdict["english_rule_fits"] = verdict["english_rule_max_width_px"] <= layout.box_width
    entry = {
        "font_id": candidate.font_id,
        "family": info.family or candidate.family,
        "style": info.style,
        "source": unpacked["package"],
        "file": {"name": font_path.name, "sha256": unpacked["font_sha256"]},
        "license": unpacked["license"],
        "metrics": metrics,
        "coverage": coverage_cases,
        "wrap": wrap_cases,
        "render": render_cases,
        "verdict": verdict,
    }
    return entry, findings


def summary_markdown(result: dict) -> str:
    run = result["run"]
    layout = result["layout"]
    box = layout["box"]
    lines = [
        f"## Font caption probe: {run['runner'] or run['os']} ({run['machine']})",
        "",
        (
            f"Layout {layout['width']}x{layout['height']}, caption box {box['width']}x{box['height']} "
            f"at ({box['x']}, {box['y']}), font {layout['font_size']} px, "
            f"line height {layout['line_height']} px, {layout['max_lines']} lines. "
            f"Layout engine: {run['layout_engine']}."
        ),
        "",
        "| Font | Missing glyph cases | Korean 14 | English 28 | Worst 28 Latin | Two lines | PNG digests |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for font in result["fonts"]:
        verdict = font["verdict"]
        missing = ", ".join(verdict["missing_glyph_cases"]) or "none"
        korean = (
            "fits"
            if verdict["korean_rule_fits"]
            else f"overflows {verdict['korean_rule_max_width_px']:.0f} px"
        )
        english = (
            "fits"
            if verdict["english_rule_fits"]
            else f"overflows {verdict['english_rule_max_width_px']:.0f} px"
        )
        worst = f"{verdict['latin_rule_worst_width_px']:.0f} px"
        two_lines = "fits" if verdict["caption_fits_two_lines"] else "needs more"
        lines.append(
            f"| {font['family']} | {missing} | {korean} | {english} | {worst} | {two_lines} | {len(font['render'])} |"
        )
    lines += ["", f"Findings recorded in result.json: {result['finding_count']}.", ""]
    return "\n".join(lines)


def build_result(layout: render.Layout, out_dir: Path, work_dir: Path, skip_png: bool) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    findings = []
    for candidate in candidates.CANDIDATES:
        entry, font_findings = probe_font(candidate, work_dir, layout, out_dir, skip_png)
        entries.append(entry)
        findings.extend(font_findings)
    result = {
        "schema_version": 1,
        "probe": "font-caption",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run": environment(),
        "layout": layout.as_dict(),
        "cases": [texts.describe(case) for case in texts.CASES],
        "fonts": entries,
        "findings": findings,
        "finding_count": len(findings),
    }
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(summary_markdown(result), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    created_work = args.work_dir is None
    work_dir = args.work_dir or Path(tempfile.mkdtemp(prefix="font-probe-"))
    out_dir = args.out_dir or Path(tempfile.mkdtemp(prefix="font-probe-out-"))
    layout = render.Layout(font_size=args.font_size, line_height=args.line_height)
    try:
        result = build_result(layout, out_dir, work_dir, args.skip_png)
    except (candidates.SourceError, TTLibError, OSError) as error:
        print(f"probe: {error}", file=sys.stderr)
        return 1
    finally:
        if created_work and not args.keep_downloads:
            shutil.rmtree(work_dir, ignore_errors=True)
    print(summary_markdown(result))
    print(f"result: {out_dir / 'result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
