"""Tests for scripts/check_public_docs.py.

Forbidden strings are assembled from pieces so that this file stays clean
when the repository scans its own diff.
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

import _helpers
import check_public_docs

EM = "\u2014"
INTERNAL_PATH = "/ho" + "me/someone/notes"
INTERNAL_FOLDER = "Home" + "base"
TOOL = "task" + "watch"
PERSONAL_QUOTE = "사용자 11/13 「" + "좋아」"
DECISION_DATE = "결정(2026-11-13 " + "수락)"
RESEARCH_LINK = "research" + "-20261113/notes.md"

ADR_INDEX = "# 결정 기록\n\n| ADR | 결정 |\n|---|---|\n| [0001](0001-first.md) | 첫 결정 |\n"
ADR = "# 0001 첫 결정\n\n## Status\n\nAccepted\n\n## Date\n\n2026-11-14\n\n## Context\n\n이유 한 줄이다.\n"


class CheckPublicDocsTest(unittest.TestCase):
    def tree(self, files: dict[str, str]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _helpers.write_tree(root, files)
        return root

    def problems(self, files: dict[str, str]) -> list[str]:
        return check_public_docs.check(self.tree(files))

    def assert_clean(self, files: dict[str, str]) -> None:
        self.assertEqual(self.problems(files), [])

    def assert_one(self, files: dict[str, str], *needles: str) -> None:
        found = self.problems(files)
        self.assertEqual(len(found), 1, found)
        for needle in needles:
            self.assertIn(needle, found[0])

    # public text

    def test_public_text_fails_on_internal_path(self):
        self.assert_one({"docs/a.md": f"See {INTERNAL_PATH} for more.\n"}, "docs/a.md:1", "internal path")

    def test_public_text_fails_on_internal_folder_name(self):
        self.assert_one({"docs/a.md": f"# T\n\nSee {INTERNAL_FOLDER} notes.\n"}, "docs/a.md:3", "internal path")

    def test_public_text_fails_on_research_link_text(self):
        self.assert_one({"docs/a.md": f"Source is `{RESEARCH_LINK}`.\n"}, "internal path")

    def test_public_text_fails_on_personal_quote_with_date(self):
        self.assert_one({"docs/a.md": f"- 결정({PERSONAL_QUOTE}): 하나를 고른다.\n"}, "personal quote")

    def test_public_text_fails_on_decision_date(self):
        self.assert_one({"docs/a.md": f"{DECISION_DATE}: 하나를 고른다.\n"}, "personal quote")

    def test_public_text_fails_on_personal_tool_name(self):
        self.assert_one({"CONTRIBUTING.md": f"Run it with {TOOL} first.\n"}, "personal tool")

    def test_public_text_fails_on_land_flag(self):
        self.assert_one({"CONTRIBUTING.md": "Submit with " + "land" + ": true.\n"}, "personal tool")

    def test_public_text_checks_the_pr_template_and_workflows(self):
        found = self.problems(
            {
                ".github/pull_request_template.md": f"## 무엇을 왜\n\n{TOOL}\n",
                ".github/workflows/ci.yml": f"name: CI\n# {INTERNAL_PATH}\n",
                "cubic.yaml": f"# {TOOL}\nversion: 1\n",
            }
        )
        self.assertEqual(len(found), 3, found)

    def test_public_text_checks_adr_files_too(self):
        files = {"docs/decisions/README.md": ADR_INDEX, "docs/decisions/0001-first.md": ADR + f"\n{INTERNAL_PATH}\n"}
        self.assert_one(files, "0001-first.md")

    def test_public_text_allows_iso_dates_in_adr(self):
        self.assert_clean({"docs/decisions/README.md": ADR_INDEX, "docs/decisions/0001-first.md": ADR})

    def test_public_text_allows_ordinary_words(self):
        self.assert_clean({"docs/a.md": "The landing page lands users on a home screen.\n"})

    # markdown line rules

    def test_markdown_fails_on_soft_break_in_paragraph(self):
        self.assert_one({"docs/a.md": "First line\nsecond line.\n"}, "docs/a.md:1", "soft line break")

    def test_markdown_fails_on_soft_break_in_list_item(self):
        self.assert_one({"docs/a.md": "# T\n\n- item\n  continued\n- other\n"}, "docs/a.md:3")

    def test_markdown_reports_the_line_of_a_later_soft_break(self):
        self.assert_one({"docs/a.md": "# T\n\nok line\n\nA\nB\n"}, "docs/a.md:5")

    def test_markdown_fails_on_em_dash_in_paragraph(self):
        self.assert_one({"docs/a.md": f"one {EM} two.\n"}, "em-dash")

    def test_markdown_fails_on_em_dash_in_list_item_and_heading(self):
        found = self.problems({"docs/a.md": f"# Title {EM} sub\n\n- item {EM} more\n"})
        self.assertEqual(len(found), 2, found)

    def test_markdown_ignores_code_blocks(self):
        text = f"```sh\nfirst\nsecond {EM}\n```\n\n    indented\n    code {EM}\n\nUse `a {EM} b` inline.\n"
        self.assert_clean({"docs/a.md": text})

    def test_markdown_ignores_tables_and_html_blocks(self):
        text = f"| a | b |\n|---|---|\n| x {EM} y | z |\n\n<div>\nraw\nhtml\n</div>\n"
        self.assert_clean({"docs/a.md": text})

    def test_markdown_ignores_front_matter(self):
        self.assert_clean({"docs/a.md": f"---\ntitle: a\nnote: b {EM} c\n---\n\nBody line.\n"})

    def test_markdown_allows_deliberate_hard_breaks(self):
        self.assert_clean({"docs/a.md": "End with two spaces  \nnext\\\nlast\n"})

    def test_markdown_skips_generated_files(self):
        files = {"frontend/src/shared/api/generated/README.md": f"a\nb {EM}\n"}
        self.assert_clean(files)

    def test_markdown_applies_to_markdown_outside_docs(self):
        self.assert_one({"README.md": "a\nb\n"}, "README.md:1")

    # links

    def test_links_pass_for_existing_files_and_anchors(self):
        files = {
            "docs/a.md": "See [b](b.md#10-sec-ond) and [self](#top) and [web](https://example.invalid/x).\n\n# Top\n",
            "docs/b.md": "# B\n\n## 10. Sec ond\n",
        }
        self.assert_clean(files)

    def test_links_resolve_self_anchors_with_relative_root(self):
        root = self.tree({"docs/a.md": "# Top\n\nSee [self](#top).\n"})
        parser = check_public_docs.make_parser()
        relative_root = Path(os.path.relpath(root))
        tokens = parser.parse((root / "docs/a.md").read_text())
        self.assertEqual(check_public_docs.check_links(relative_root, "docs/a.md", tokens, {}, parser), [])

    def test_links_fail_for_missing_file(self):
        self.assert_one({"docs/a.md": "See [b](missing.md).\n"}, "broken relative link")

    def test_links_fail_for_missing_anchor(self):
        files = {"docs/a.md": "See [b](b.md#nope).\n", "docs/b.md": "# B\n"}
        self.assert_one(files, "missing anchor")

    def test_links_fail_when_leaving_the_repository(self):
        self.assert_one({"docs/a.md": "See [x](../../outside.md).\n"}, "leaves the repository")

    def test_links_ignore_html_comments(self):
        self.assert_clean({"docs/a.md": "# A\n\n<!-- ADR: [x](docs/missing.md) -->\n"})

    # ADR index

    def test_adr_index_fails_when_a_file_is_not_listed(self):
        files = {
            "docs/decisions/README.md": ADR_INDEX,
            "docs/decisions/0001-first.md": ADR,
            "docs/decisions/0002-second.md": ADR,
        }
        self.assert_one(files, "0002-second.md")

    def test_adr_index_fails_when_a_listed_file_is_missing(self):
        self.assert_one({"docs/decisions/README.md": ADR_INDEX}, "broken relative link")

    def test_adr_index_passes_when_listed_files_exist(self):
        self.assert_clean({"docs/decisions/README.md": ADR_INDEX, "docs/decisions/0001-first.md": ADR})

    def test_adr_index_rejects_mentions_without_links(self):
        for mention in ("0001-first.md", "`0001-first.md`", "```\n[x](0001-first.md)\n```", "![x](0001-first.md)", "[x](https://example.invalid/0001-first.md)", "[x](../0001-first.md)"):
            with self.subTest(mention=mention):
                root = self.tree({"docs/decisions/README.md": "# Index\n\n" + mention + "\n", "docs/decisions/0001-first.md": ADR})
                self.assertEqual(check_public_docs.check_adr_index(root, ["docs/decisions/README.md", "docs/decisions/0001-first.md"]), ["docs/decisions/README.md: 0001-first.md is not listed in the index"])

    def test_adr_index_accepts_resolved_reference_links(self):
        index = "# Index\n\n[First][adr]\n\n[adr]: ./0001-first.md#context\n"
        self.assert_clean({"docs/decisions/README.md": index, "docs/decisions/0001-first.md": ADR})

    def test_adr_index_allows_deleted_tracked_records(self):
        root = self.tree({"docs/decisions/README.md": "# Decisions\n"})
        files = ["docs/decisions/README.md", "docs/decisions/0001-retired.md"]
        self.assertEqual(check_public_docs.check_adr_index(root, files), [])

    # command line

    def test_main_exit_codes_follow_the_result(self):
        good = self.tree({"docs/a.md": "One line.\n"})
        bad = self.tree({"docs/a.md": "Two\nlines.\n"})
        for root, expected in ((good, 0), (bad, 1)):
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(check_public_docs.main(["--root", str(root)]), expected)


if __name__ == "__main__":
    unittest.main()
