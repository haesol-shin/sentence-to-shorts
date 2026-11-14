"""Exercise message formatting and full PR commit ranges."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import _helpers
import check_commit_messages as checker

VALID = "fix(cache): retain speech audio\n\n- Avoid synthesis for caption-only edits\n- Keep approved speech available\n"


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

    def test_message_limits_bullet_count(self):
        prefix = "fix(cache): retain audio\n\n"
        self.assertEqual(checker.check_message(prefix + "\n".join(f"- Reason {n}" for n in range(5))), [])
        self.assertTrue(checker.check_message(prefix + "\n".join(f"- Reason {n}" for n in range(6))))

    def test_range_checks_earlier_commits_not_only_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = dict(os.environ, GIT_AUTHOR_NAME="Example", GIT_AUTHOR_EMAIL="test@example.invalid",
                       GIT_COMMITTER_NAME="Example", GIT_COMMITTER_EMAIL="test@example.invalid")

            def run(*args, text=None):
                return subprocess.run(["git", *args], cwd=root, env=env, input=text,
                                      text=True, capture_output=True, check=True).stdout.strip()

            run("init", "--quiet")
            tree = run("mktree", text="")
            base = run("commit-tree", tree, text=VALID)
            bad = run("commit-tree", tree, "-p", base, text="missing format\n")
            head = run("commit-tree", tree, "-p", bad, text=VALID)
            script = Path(checker.__file__).resolve()
            result = subprocess.run([os.sys.executable, str(script), "--range", f"{base}..{head}"],
                                    cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn(bad, result.stderr)
            self.assertNotIn(head, result.stderr)
            passed = subprocess.run([os.sys.executable, str(script), "--range", f"{bad}..{head}"],
                                    cwd=root, capture_output=True, text=True)
            self.assertEqual(passed.returncode, 0, passed.stderr)


if __name__ == "__main__":
    unittest.main()
