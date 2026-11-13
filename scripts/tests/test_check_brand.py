"""Tests for scripts/check_brand.py. Names here are synthetic."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import _helpers
import check_brand

NAME = "example-brand-name"
KO_NAME = "예시이름"

BRAND = f"display_name_ko: {KO_NAME}\ndisplay_name_en: {NAME}\nrepository: {NAME}\napp_id: app\n"
ALLOWED = {
    "LICENSE": f"license text for {NAME}\n",
    "README.md": f"# {NAME}\n",
    "README.ko.md": f"# {KO_NAME}\n",
}


class CheckBrandTest(unittest.TestCase):
    def tree(self, files: dict[str, str]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _helpers.write_tree(root, files)
        return root

    def run_main(self, root: Path) -> tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = check_brand.main(["--root", str(root)])
        return code, err.getvalue()

    def test_brand_passes_when_names_stay_in_allowlist(self):
        root = self.tree({"core/config/brand.yaml": BRAND, **ALLOWED, "docs/a.md": "Neutral text.\n"})
        self.assertEqual(check_brand.check(root), [])
        self.assertEqual(self.run_main(root)[0], 0)

    def test_brand_fails_when_english_name_repeats_in_another_file(self):
        root = self.tree({"core/config/brand.yaml": BRAND, "docs/a.md": f"line one\nUse {NAME} here.\n"})
        problems = check_brand.check(root)
        self.assertEqual(len(problems), 1)
        self.assertIn("docs/a.md:2", problems[0])
        code, err = self.run_main(root)
        self.assertEqual(code, 1)
        self.assertIn(NAME, err)

    def test_brand_fails_when_korean_display_name_repeats(self):
        root = self.tree({"core/config/brand.yaml": BRAND, "docs/a.md": f"{KO_NAME}로 시작한다.\n"})
        self.assertEqual(len(check_brand.check(root)), 1)

    def test_brand_fails_when_name_is_in_a_file_path(self):
        root = self.tree({"core/config/brand.yaml": BRAND, f"docs/{NAME}.txt": "x\n"})
        problems = check_brand.check(root)
        self.assertEqual(len(problems), 1)
        self.assertIn("path", problems[0])

    def test_brand_ignores_the_placeholder_app_id(self):
        root = self.tree({"core/config/brand.yaml": BRAND, "docs/a.md": "The app stores data per app.\n"})
        self.assertEqual(check_brand.check(root), [])

    def test_brand_rejects_name_copies_in_decision_records(self):
        for record in ("0001-example.md", "0021-defer-brand-name-to-team.md"):
            with self.subTest(record=record):
                root = self.tree({"core/config/brand.yaml": BRAND, f"docs/decisions/{record}": NAME})
                self.assertEqual(len(check_brand.check(root)), 1)

    def test_brand_checks_a_real_app_id(self):
        brand = BRAND.replace("app_id: app", "app_id: exid")
        root = self.tree({"core/config/brand.yaml": brand, "docs/a.md": "Path is exid/data.\n"})
        self.assertEqual(len(check_brand.check(root)), 1)

    def test_brand_fails_when_a_value_is_empty(self):
        brand = BRAND.replace(f"repository: {NAME}", 'repository: ""')
        root = self.tree({"core/config/brand.yaml": brand})
        problems = check_brand.check(root)
        self.assertEqual(len(problems), 1)
        self.assertIn("repository", problems[0])

    def test_brand_fails_when_a_key_is_missing(self):
        brand = "display_name_ko: a\ndisplay_name_en: b\nrepository: c\n"
        root = self.tree({"core/config/brand.yaml": brand})
        self.assertIn("app_id", check_brand.check(root)[0])

    def test_brand_fails_when_the_brand_file_is_missing(self):
        root = self.tree({"docs/a.md": "x\n"})
        self.assertEqual(len(check_brand.check(root)), 1)

    def test_brand_reads_quoted_values_and_comments(self):
        brand = f"# names\ndisplay_name_ko: '{KO_NAME}'\ndisplay_name_en: \"{NAME}\"  # english\nrepository: {NAME}\napp_id: app\n"
        values = check_brand.parse_brand(brand)
        self.assertEqual(values["display_name_en"], NAME)
        self.assertEqual(values["display_name_ko"], KO_NAME)

    def test_brand_skips_binary_files(self):
        root = self.tree({"core/config/brand.yaml": BRAND})
        (root / "logo.png").write_bytes(b"\xff\xfe\x00" + NAME.encode() + b"\x80")
        self.assertEqual(check_brand.check(root), [])


if __name__ == "__main__":
    unittest.main()
