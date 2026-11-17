"""Exercise the fast check: the order, the test selection, and the failure report."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import _helpers  # noqa: F401  (puts scripts/ on sys.path)
import check_fast

SHA = "0" * 40


def fake_runner(overrides=None, capture=None, select="tests/contracts\n"):
    """Answer the command probes, record every call, and read the squash message."""
    calls = []

    def runner(argv, cwd):
        argv = [str(part) for part in argv]
        calls.append((argv, Path(cwd)))
        if capture is not None and "--message-file" in argv:
            path = argv[argv.index("--message-file") + 1]
            capture["message"] = Path(path).read_text(encoding="utf-8")
        for probe, reply in (overrides or {}).items():
            if probe in argv:
                return reply
        if "merge-base" in argv:
            return 0, f"{SHA}\n"
        if "--name-only" in argv:
            return 0, "docs/INTENT.md\n"
        if check_fast.SELECTOR in argv:
            return 0, select
        return 0, ""

    runner.calls = calls
    return runner


class CheckFastTest(unittest.TestCase):
    def run_fast(self, *args, runner):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_fast.main([str(arg) for arg in args], runner=runner)
        return code, out.getvalue()

    def test_clean_tree_prints_ok(self):
        code, out = self.run_fast(runner=fake_runner())
        self.assertEqual(code, 0)
        self.assertIn("fast check: ok", out)

    def test_lint_failure_exits_one_and_names_ruff(self):
        runner = fake_runner({"ruff": (1, "core/app/example.py:1:1: F401 unused\n")})
        code, out = self.run_fast(runner=runner)
        self.assertEqual(code, 1)
        self.assertIn("== ruff: failed (exit 1)", out)
        self.assertIn("fast check: failed: ruff", out)

    def test_unmapped_path_stays_in_ci(self):
        runner = fake_runner({check_fast.SELECTOR: (0, "tests\n")})
        code, out = self.run_fast(runner=runner)
        self.assertEqual(code, 0)
        self.assertIn("== tests: CI only", out)
        self.assertFalse([argv for argv, _ in runner.calls if "pytest" in argv])

    def test_selected_targets_run_with_the_ci_markers(self):
        runner = fake_runner(select="tests/contracts\ntests/story\n")
        code, _ = self.run_fast(runner=runner)
        self.assertEqual(code, 0)
        call = next(argv for argv, _ in runner.calls if "pytest" in argv)
        self.assertEqual(
            call[3:],
            [
                "tests/contracts",
                "tests/story",
                "-q",
                "-rfE",
                "-m",
                "not sandbox and not models and not realllm",
            ],
        )

    def test_commit_checks_run_in_fixed_order_and_join_the_squash_message(self):
        capture = {}
        with tempfile.TemporaryDirectory() as tmp:
            title = Path(tmp) / "title.txt"
            title.write_text("feat(ui): add a frame\n", encoding="utf-8")
            body = Path(tmp) / "commit.txt"
            body.write_text("- Add a frame component\n- Keep the tokens\n", encoding="utf-8")
            runner = fake_runner(capture=capture)
            code, _ = self.run_fast(
                "--title-file", title, "--squash-file", body, runner=runner
            )
        self.assertEqual(code, 0)
        modes = [
            argv[argv.index(check_fast.COMMIT_CHECK) + 1]
            for argv, _ in runner.calls
            if check_fast.COMMIT_CHECK in argv
        ]
        self.assertEqual(modes, ["--range", "--pr-title", "--message-file"])
        self.assertEqual(
            capture["message"],
            "feat(ui): add a frame\n\n- Add a frame component\n- Keep the tokens\n",
        )

    def test_generated_file_diff_reads_only_the_generated_paths(self):
        runner = fake_runner()
        self.run_fast(runner=runner)
        call = next(
            argv for argv, _ in runner.calls if "diff" in argv and "--exit-code" in argv
        )
        self.assertEqual(
            call[-len(check_fast.GENERATED_PATHS) :], list(check_fast.GENERATED_PATHS)
        )

    def test_missing_base_stops_before_any_check(self):
        runner = fake_runner({"merge-base": (1, "fatal: unknown revision\n")})
        code, out = self.run_fast("--base", "origin/main", runner=runner)
        self.assertEqual(code, 1)
        self.assertIn("cannot resolve --base origin/main", out)
        self.assertFalse([argv for argv, _ in runner.calls if "pytest" in argv])


if __name__ == "__main__":
    unittest.main()
