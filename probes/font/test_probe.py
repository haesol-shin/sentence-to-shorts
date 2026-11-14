"""Unit checks for the caption probe harness.

The harness runs on a machine that has no candidate fonts, so the checks use a
synthetic width function and synthetic result files. They cover the parts that
would otherwise fail only in CI: cluster aware wrapping, the rule comparison,
the cmap verdict, the digest contract and the run pairing.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

import candidates
import compare
import coverage
import render
import texts
import wrap


def fixed_width(char_px: int):
    return lambda text: len(text) * char_px


class GraphemeTest(unittest.TestCase):
    def test_grapheme_split_keeps_zwj_and_keycap_sequences_whole(self):
        clusters = texts.split_clusters("가\u0301 👨‍👩‍👧‍👦 1️⃣")
        self.assertEqual(clusters, ["가\u0301", " ", "👨‍👩‍👧‍👦", " ", "1️⃣"])

    def test_grapheme_split_joins_decomposed_hangul(self):
        decomposed = texts.CASE_BY_ID["jamo"].text
        self.assertEqual(len(texts.split_clusters(decomposed)), 2)
        self.assertGreater(len(decomposed), 2)


class WrapTest(unittest.TestCase):
    def test_wrap_rule_line_count_uses_cluster_limit(self):
        self.assertEqual(len(wrap.rule_lines(["가"] * 14, 14)), 1)
        self.assertEqual(len(wrap.rule_lines(["가"] * 15, 14)), 2)
        self.assertEqual(len(wrap.rule_lines(["a"] * 28, 28)), 1)
        self.assertEqual(len(wrap.rule_lines(["a"] * 29, 28)), 2)

    def test_wrap_pixel_break_prefers_word_boundary(self):
        lines = wrap.pixel_lines(["a", "a", " ", "b", "b", "b"], 55, fixed_width(10))
        self.assertEqual(["".join(line) for line in lines], ["aa", "bbb"])

    def test_wrap_pixel_hard_breaks_a_word_wider_than_the_box(self):
        lines = wrap.pixel_lines(list("abcdef"), 25, fixed_width(10))
        self.assertEqual(["".join(line) for line in lines], ["ab", "cd", "ef"])
        self.assertTrue(all(len("".join(line)) * 10 <= 25 for line in lines))

    def test_wrap_pixel_keeps_a_combining_mark_on_its_base(self):
        clusters = texts.split_clusters("가\u0301가\u0301")
        lines = wrap.pixel_lines(clusters, 12, fixed_width(10))
        self.assertEqual(lines, [["가\u0301"], ["가\u0301"]])
        self.assertTrue(all(not line[0].startswith("\u0301") for line in lines))

    def test_wrap_compare_flags_the_character_rule_that_overflows(self):
        measured = wrap.compare(texts.CASE_BY_ID["en_identifier"], fixed_width(40), 900, 2)
        self.assertTrue(measured["rule_overflow"])
        self.assertGreater(measured["rule_line_width_px"][0], 900)
        self.assertEqual(measured["rule_line_count"], 2)
        self.assertEqual(measured["pixel_line_count"], 2)
        self.assertTrue(measured["agrees"])
        self.assertTrue(measured["fits"])

    def test_wrap_rule_line_width_ignores_edge_whitespace(self):
        self.assertEqual(wrap.normalized("  가  나 "), "가 나")
        measured = wrap.compare(texts.CASE_BY_ID["ko_long"], fixed_width(10), 900, 2)
        self.assertTrue(measured["rule_lines"])
        self.assertFalse(any(text != text.strip() for text in measured["rule_lines"]))

    def test_wrap_compare_agrees_when_one_line_holds_the_text(self):
        measured = wrap.compare(texts.CASE_BY_ID["emoji"], fixed_width(10), 900, 2)
        self.assertEqual(measured["rule_line_count"], 1)
        self.assertEqual(measured["pixel_line_count"], 1)
        self.assertTrue(measured["agrees"])
        self.assertFalse(measured["rule_overflow"])


class CoverageTest(unittest.TestCase):
    def test_coverage_reports_each_missing_codepoint_once(self):
        missing = coverage.missing_glyphs({ord("a"): "a"}, "ab😀b")
        self.assertEqual([item["codepoint"] for item in missing], ["U+0062", "U+1F600"])
        self.assertEqual(missing[1]["name"], "GRINNING FACE")


class SourceTest(unittest.TestCase):
    def test_source_verify_rejects_a_digest_that_does_not_match(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file.bin"
            path.write_bytes(b"probe")
            expected = hashlib.sha256(b"probe").hexdigest()
            self.assertEqual(candidates.verify_file(path, expected), expected)
            with self.assertRaises(candidates.SourceError):
                candidates.verify_file(path, "0" * 64)


class LayoutTest(unittest.TestCase):
    def test_layout_baselines_stay_inside_the_caption_box(self):
        layout = render.Layout()
        lines = render.baselines(layout, ascent=64, descent=11, count=2)
        self.assertEqual(len(lines), 2)
        self.assertLess(lines[0], lines[1])
        self.assertGreaterEqual(lines[0] - 64, layout.box_y)
        self.assertLessEqual(lines[-1] + 11, layout.box_y + layout.box_height)

    def test_layout_baselines_center_a_font_with_a_large_descent(self):
        layout = render.Layout()
        lines = render.baselines(layout, ascent=61, descent=16, count=2)
        self.assertGreaterEqual(lines[0] - 61, layout.box_y)
        self.assertLessEqual(lines[-1] + 16, layout.box_y + layout.box_height)


class DigestTest(unittest.TestCase):
    def test_digest_is_stable_for_the_same_pixels(self):
        image = Image.new("RGB", (16, 16), (0, 0, 0))
        ImageDraw.Draw(image).rectangle((4, 4, 8, 8), fill=(255, 255, 255))
        self.assertEqual(render.digests(image), render.digests(image))
        other = Image.new("RGB", (16, 16), (0, 0, 0))
        self.assertNotEqual(render.digests(image)["pixels_sha256"], render.digests(other)["pixels_sha256"])


def synthetic_result(label: str, pixels: str, png: str) -> dict:
    return {
        "run": {"runner": label, "freetype": "2.14.3", "layout_engine": "raqm", "raqm": "0.11.0"},
        "layout": {"font_size": 64},
        "fonts": [
            {
                "font_id": "fake",
                "file": {"sha256": "a" * 64},
                "render": {"case": {"pixels_sha256": pixels, "png_sha256": png, "png": None}},
            }
        ],
    }


class CompareTest(unittest.TestCase):
    def test_compare_reports_equal_runs_as_one_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = [
                compare.Run("linux", synthetic_result("linux", "p" * 64, "f" * 64), root),
                compare.Run("windows", synthetic_result("windows", "p" * 64, "f" * 64), root),
            ]
            comparison = compare.build_comparison(runs, lambda *args: {})
            self.assertEqual(comparison["summary"], {"run_count": 2, "equal": 1, "different": 0, "pending": 0})
            self.assertEqual(comparison["pairs"][0]["status"], "equal")

    def test_compare_records_a_different_pair_with_causes(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = [
                compare.Run("linux", synthetic_result("linux", "p" * 64, "f" * 64), root),
                compare.Run("windows", synthetic_result("windows", "q" * 64, "g" * 64), root),
            ]

            def diff_writer(font_id, case_id, png_a, png_b):
                calls.append((font_id, case_id, png_a, png_b))
                return {"diff_png": None, "note": "source PNG missing"}

            comparison = compare.build_comparison(runs, diff_writer)
            self.assertEqual(comparison["summary"]["different"], 1)
            pair = comparison["pairs"][0]
            self.assertFalse(pair["pixels_equal"])
            self.assertTrue(pair["cause_candidates"])
            self.assertEqual(calls, [("fake", "case", None, None)])

    def test_compare_marks_a_single_run_as_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = [compare.Run("linux", synthetic_result("linux", "p" * 64, "f" * 64), root)]
            comparison = compare.build_comparison(runs, lambda *args: {})
            self.assertEqual(comparison["summary"]["run_count"], 1)
            self.assertEqual(comparison["summary"]["pending"], 1)
            self.assertEqual(comparison["pairs"], [])


if __name__ == "__main__":
    unittest.main()
