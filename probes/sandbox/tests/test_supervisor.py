"""Unit checks for the parent supervisor and its verdict classes."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import run_probe

HERE = Path(__file__).resolve().parent
STUB = HERE / "stub_deno"
LIMITS = {
    "wall_ms": 5000,
    "stdout_bytes": 4096,
    "stderr_bytes": 4096,
    "request_bytes": 65536,
}


def run_case(run_id: str, expect: str, memory_cap: dict | None = None, **overrides):
    program = {
        "id": run_id,
        "expect": expect,
        "output": "json",
        "contain": "memory" if run_id == "stub_memory" else None,
    }
    limits = dict(LIMITS)
    limits.update(overrides)
    request = json.dumps({"protocol": 1, "run_id": run_id}).encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="probe-test-") as workdir:
        outcome = run_probe.supervise(
            [sys.executable, str(STUB)],
            request,
            limits,
            Path(workdir),
            None,
            None,
        )
    return run_probe.classify(
        program, {"outcome": outcome, "request_bytes": len(request)}, memory_cap or {"applied": False}
    )


class SupervisorTests(unittest.TestCase):
    def test_supervisor_kills_on_wall_timeout(self):
        result = run_case("stub_sleep", "reject", wall_ms=300)
        self.assertEqual(result["verdict"], "timeout")
        self.assertTrue(result["met"])
        self.assertLess(result["wall_ms"], 4000)

    def test_supervisor_caps_stdout(self):
        result = run_case("stub_flood", "reject", stdout_bytes=1024)
        self.assertEqual(result["verdict"], "output_limit")
        self.assertTrue(result["met"])
        self.assertLessEqual(len(str(result["detail"])), 400)

    def test_supervisor_reads_permission_denial_as_rejection(self):
        result = run_case("stub_reject", "reject")
        self.assertEqual(result["verdict"], "rejected")
        self.assertTrue(result["met"])
        self.assertIn("Requires read access", result["detail"])

    def test_supervisor_records_unexpected_success_as_escape(self):
        result = run_case("stub_escape", "reject")
        self.assertEqual(result["verdict"], "escape")
        self.assertFalse(result["met"])

    def test_supervisor_accepts_expectation_for_normal_program(self):
        result = run_case("stub_pass", "pass")
        self.assertEqual(result["verdict"], "passed")
        self.assertTrue(result["met"])

    def test_supervisor_rejects_invalid_media_payload(self):
        result = run_case("stub_png_bad", "reject")
        self.assertEqual(result["verdict"], "invalid_output")
        self.assertTrue(result["met"])

    def test_supervisor_accepts_valid_media_payload(self):
        program = {
            "id": "stub_png_ok",
            "expect": "pass",
            "output": "png",
            "contain": None,
        }
        request = json.dumps({"protocol": 1, "run_id": "stub_png_ok"}).encode("utf-8")
        with tempfile.TemporaryDirectory(prefix="probe-test-") as workdir:
            outcome = run_probe.supervise(
                [sys.executable, str(STUB)],
                request,
                LIMITS,
                Path(workdir),
                None,
                None,
            )
        result = run_probe.classify(program, {"outcome": outcome}, {"applied": False})
        self.assertEqual(result["verdict"], "passed", result["detail"])

    def test_supervisor_flags_two_protocol_lines(self):
        result = run_case("stub_two_lines", "reject")
        self.assertEqual(result["verdict"], "harness_error")

    def test_supervisor_records_missing_protocol_line(self):
        result = run_case("stub_unknown", "reject")
        self.assertEqual(result["verdict"], "crashed")
        self.assertFalse(result["met"])

    @unittest.skipUnless(os.name == "posix", "signal death check is POSIX only")
    def test_supervisor_counts_memory_kill_only_with_cap(self):
        capped = run_case("stub_memory", "reject", memory_cap={"applied": True})
        self.assertEqual(capped["verdict"], "memory_limit")
        self.assertTrue(capped["met"])
        uncapped = run_case("stub_memory", "reject", memory_cap={"applied": False})
        self.assertEqual(uncapped["verdict"], "crashed")
        self.assertFalse(uncapped["met"])


if __name__ == "__main__":
    unittest.main()
