"""Exercise message formatting and full PR commit ranges."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import _helpers  # noqa: F401  (puts scripts/ on sys.path)
import check_commit_messages as checker

VALID = "fix(cache): retain speech audio\n\n- Avoid synthesis for caption-only edits\n- Keep approved speech available\n"


def _git(cwd, *args, text=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="Example", GIT_AUTHOR_EMAIL="test@example.invalid",
               GIT_COMMITTER_NAME="Example", GIT_COMMITTER_EMAIL="test@example.invalid")
    return subprocess.run(["git", *args], cwd=cwd, env=env, input=text,
                          text=True, capture_output=True, check=True).stdout.strip()


class CommitMessagesTest(unittest.TestCase):
    def test_message_accepts_regular_and_breaking_commits(self):
        for message in (VALID, VALID.replace("fix(cache):", "fix(cache)!:")):
            with self.subTest(message=message):
                self.assertEqual(checker.check_message(message), [])

    def test_message_rejects_missing_scope_body_and_blank_separator(self):
        for message in (
            "fix: retain audio\n\n- Avoid synthesis\n",
            "fix(cache): retain audio\n",
            "fix(cache): retain audio\n- Avoid synthesis\n",
            "fix(cache): retain audio\n\n\n- Avoid synthesis\n",
            "fix(cache): 오디오 유지\n\n- Avoid synthesis\n",
        ):
            with self.subTest(message=message):
                self.assertTrue(checker.check_message(message))

    def test_message_rejects_wrapping_blank_bullets_and_trailers(self):
        for body in (
            "- Avoid synthesis\n  when captions change",
            "- Avoid synthesis\n\n- Retain audio",
            "- ",
            "- Avoid synthesis\nSigned-off-by: Example",
        ):
            with self.subTest(body=body):
                self.assertTrue(checker.check_message("fix(cache): retain audio\n\n" + body))

    def test_message_enforces_exact_character_boundary(self):
        prefix = "fix(cache): retain audio\n\n- "
        self.assertEqual(checker.check_message(prefix + "x" * 70), [])
        self.assertTrue(checker.check_message(prefix + "x" * 71))

    def test_title_enforces_the_pattern_and_72_characters(self):
        longest = "ci(repo): " + "x" * (checker.MAX_TITLE - len("ci(repo): "))
        self.assertEqual(len(longest), checker.MAX_TITLE)
        self.assertEqual(checker.check_title(longest), [])
        self.assertTrue(checker.check_title(longest + "x"))
        for title in ("ci: add gate", "ci(repo): 게이트 추가", "CI(repo): add gate", "ci(repo): "):
            with self.subTest(title=title):
                self.assertTrue(checker.check_title(title))

    def test_pr_title_option_reports_a_bad_title(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(checker.main(["--pr-title", "fix(cache): retain audio"]), 0)
            self.assertEqual(checker.main(["--pr-title", "add ci"]), 1)

    def test_message_limits_bullet_count(self):
        prefix = "fix(cache): retain audio\n\n"
        self.assertEqual(checker.check_message(prefix + "\n".join(f"- Reason {n}" for n in range(5))), [])
        self.assertTrue(checker.check_message(prefix + "\n".join(f"- Reason {n}" for n in range(6))))

    def test_range_checks_earlier_commits_not_only_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _git(root, "init", "--quiet")
            tree = _git(root, "mktree", text="")
            base = _git(root, "commit-tree", tree, text=VALID)
            bad = _git(root, "commit-tree", tree, "-p", base, text="missing format\n")
            head = _git(root, "commit-tree", tree, "-p", bad, text=VALID)
            script = Path(checker.__file__).resolve()
            result = subprocess.run([os.sys.executable, str(script), "--range", f"{base}..{head}"],
                                    cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn(bad, result.stderr)
            self.assertNotIn(head, result.stderr)
            passed = subprocess.run([os.sys.executable, str(script), "--range", f"{bad}..{head}"],
                                    cwd=root, capture_output=True, text=True)
            self.assertEqual(passed.returncode, 0, passed.stderr)

    def test_range_skips_merges_but_still_checks_regular_commits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _git(root, "init", "--quiet")
            tree = _git(root, "mktree", text="")
            base = _git(root, "commit-tree", tree, text=VALID)
            earlier = _git(root, "commit-tree", tree, "-p", base, text=VALID)
            merge = _git(root, "commit-tree", tree, "-p", earlier, "-p", base,
                         text="Merge branch 'main' into feature\n")
            good = _git(root, "commit-tree", tree, "-p", merge, text=VALID)
            bad = _git(root, "commit-tree", tree, "-p", good, text="missing format\n")
            script = Path(checker.__file__).resolve()

            def check(start, end):
                return subprocess.run([os.sys.executable, str(script), "--range", f"{start}..{end}"],
                                      cwd=root, capture_output=True, text=True)

            passed = check(base, good)
            self.assertEqual(passed.returncode, 0, passed.stderr)
            only_merge = check(earlier, merge)
            self.assertEqual(only_merge.returncode, 0, only_merge.stderr)
            failed = check(base, bad)
            self.assertEqual(failed.returncode, 1)
            self.assertIn(bad, failed.stderr)
            self.assertNotIn(merge, failed.stderr)
            empty = check(good, good)
            self.assertEqual(empty.returncode, 1)
            self.assertIn("range contains no commits", empty.stderr)


if __name__ == "__main__":
    unittest.main()
