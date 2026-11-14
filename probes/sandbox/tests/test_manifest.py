"""Checks on the program manifest and the programs that run without Pyodide."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

import run_probe
import validate

HERE = Path(__file__).resolve().parent.parent
PROGRAMS = HERE / "programs"

REQUIRED = {
    "style_parts_ok",
    "bgm_loop_ok",
    "js_bridge_sys",
    "file_read",
    "file_write",
    "network_fetch",
    "env_read",
    "subprocess",
    "ffi_dlopen",
    "permission_request",
    "remote_import",
    "infinite_loop",
    "memory_spike",
    "stdout_flood",
    "bad_png",
    "bad_wav_header",
    "overlong_wav",
    "state_leak",
}


def manifest() -> dict:
    return json.loads((HERE / "programs.json").read_text(encoding="utf-8"))


def load_program(name: str):
    spec = importlib.util.spec_from_file_location(f"probe_{name}", PROGRAMS / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ManifestTests(unittest.TestCase):
    def test_manifest_lists_every_required_program(self):
        ids = {program["id"] for program in manifest()["programs"]}
        self.assertEqual(REQUIRED - ids, set())

    def test_manifest_program_files_exist(self):
        for program in manifest()["programs"]:
            self.assertTrue((PROGRAMS / program["file"]).is_file(), program["file"])

    def test_manifest_limits_stay_within_contract(self):
        limits = manifest()["limits"]
        self.assertLessEqual(limits["wall_ms"], 60000)
        self.assertLessEqual(limits["stdout_bytes"], 48 * 1024 * 1024)
        self.assertLessEqual(limits["stderr_bytes"], 64 * 1024)
        self.assertLessEqual(limits["request_bytes"], 12 * 1024 * 1024)
        for program in manifest()["programs"]:
            self.assertIn(program["expect"], run_probe.MET)
            self.assertIn(program["output"], ("png", "wav", "json"))
            self.assertGreaterEqual(program.get("wall_ms", limits["wall_ms"]), 1)

    def test_manifest_async_programs_await_inside_the_entry(self):
        for program in manifest()["programs"]:
            if program.get("async"):
                source = (PROGRAMS / program["file"]).read_text(encoding="utf-8")
                self.assertIn("async def " + program["entry"], source, program["id"])
                self.assertIn("await ", source, program["id"])

    def test_manifest_normal_wav_program_produces_valid_wav(self):
        module = load_program("bgm_loop_ok.py")
        accepted, detail = validate.check_wav(module.render_loop({"seconds": 1}, 7))
        self.assertTrue(accepted, detail)

    def test_manifest_invalid_wav_programs_are_rejected(self):
        header = load_program("bad_wav_header.py")
        accepted, _ = validate.check_wav(header.render_loop({}, 7))
        self.assertFalse(accepted)
        overlong = load_program("overlong_wav.py")
        accepted, detail = validate.check_wav(overlong.render_loop({}, 7))
        self.assertFalse(accepted)
        self.assertIn("over", detail)

    def test_manifest_state_leak_program_reports_shared_state(self):
        module = load_program("state_leak.py")
        with tempfile.TemporaryDirectory(prefix="probe-leak-") as workdir:
            previous = os.getcwd()
            os.chdir(workdir)
            try:
                report = module.run()
            finally:
                os.chdir(previous)
        self.assertEqual(report, {"module": True, "file": True, "patch": True})


if __name__ == "__main__":
    unittest.main()
