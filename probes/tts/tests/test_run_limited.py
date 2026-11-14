"""Tests for the bounded setup command runner."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROBES = Path(__file__).resolve().parents[1]
RUN_LIMITED = PROBES / "common" / "run_limited.py"


class RunLimitedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.log = Path(self.temp.name) / "setup.log"

    def run_command(self, timeout: str, code: str) -> int:
        return subprocess.call(
            [
                sys.executable,
                str(RUN_LIMITED),
                "--timeout",
                timeout,
                "--log",
                str(self.log),
                "--",
                sys.executable,
                "-c",
                code,
            ]
        )

    def test_success_keeps_the_child_exit_code(self) -> None:
        self.assertEqual(self.run_command("10", "print('ok')"), 0)
        self.assertIn("exit 0", self.log.read_text(encoding="utf-8"))

    def test_timeout_returns_124_and_is_logged(self) -> None:
        self.assertEqual(self.run_command("0.2", "import time; time.sleep(5)"), 124)
        text = self.log.read_text(encoding="utf-8")
        self.assertIn("exceeded", text)
        self.assertIn("exit 124", text)

    def test_child_failure_is_not_turned_into_success(self) -> None:
        self.assertEqual(self.run_command("10", "raise SystemExit(7)"), 7)


if __name__ == "__main__":
    unittest.main()
