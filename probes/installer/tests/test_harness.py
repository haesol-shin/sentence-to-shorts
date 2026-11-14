"""Unit checks for the installer probe.

These run without network, without an x86_64 runner and without the bundled runtime. They
cover the manifest pins, the path rules, the packaging templates and the result shape. The
start of a real installer is measured by the workflow, not here.
"""

from __future__ import annotations

import json
import sys
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_probe import silent_flags  # noqa: E402

from harness import (  # noqa: E402
    HarnessError,
    Probe,
    ProbeError,
    deep_path,
    install_dir,
    load_manifest,
    missing_exec_modes,
    parse_port_file,
    parse_shortcut,
    parse_task_status,
    render_iss,
    render_nsi,
    require,
    summary_markdown,
    synthetic_paths,
    tar_modes,
    wait_health,
)

ROOT = Path(__file__).resolve().parents[1]


class ManifestTest(unittest.TestCase):
    def test_manifest_pins_both_platform_assets(self) -> None:
        manifest = load_manifest()
        self.assertEqual(manifest["python"]["version"], "3.11.18")
        for label in ("linux-x86_64", "windows-x86_64"):
            asset = manifest["python"]["assets"][label]
            self.assertEqual(len(asset["sha256"]), 64)
            self.assertIn(manifest["python"]["release"], asset["name"])
            self.assertIn(label.split("-")[0], asset["name"])
            self.assertGreater(asset["bytes"], 0)
            self.assertTrue(asset["url"].startswith("https://github.com/"))

    def test_manifest_lists_the_measurements(self) -> None:
        manifest = load_manifest()
        self.assertEqual(
            manifest["measurements"],
            ["download_bytes", "compressed_bytes", "installed_bytes", "install_seconds", "start_seconds"],
        )


class PathTest(unittest.TestCase):
    def test_install_path_below_localappdata_programs(self) -> None:
        path = install_dir(Path("/srv/example"), "app", "0.1.0")
        self.assertEqual(path.as_posix(), "/srv/example/Programs/app/0.1.0")

    def test_synthetic_paths_carry_hangul_and_space(self) -> None:
        linux = synthetic_paths(Path("/work"), "linux", "app", "0.1.0")
        self.assertIn("설치", linux["login_name"])
        self.assertNotIn(" ", linux["login_name"])
        self.assertIn(" ", linux["home"].name)
        self.assertIn("홈", linux["home"].name)
        windows = synthetic_paths(Path("C:/work"), "windows", "app", "0.1.0")
        self.assertIn(" ", windows["login_name"])
        self.assertTrue(str(windows["install"]).endswith("Programs/app/0.1.0") or str(windows["install"]).endswith("Programs\\app\\0.1.0"))

    def test_deep_path_reaches_the_requested_length(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "install"
            base.mkdir()
            target = deep_path(base, len(str(base)) + 120)
            self.assertEqual(len(str(target)), len(str(base)) + 120)
            self.assertTrue(str(target).startswith(str(base)))


class ArchiveTest(unittest.TestCase):
    def make_tar(self, path: Path) -> None:
        with tarfile.open(path, "w:gz") as archive:
            for name, mode, payload in (
                ("start.sh", 0o755, b"#!/bin/sh\n"),
                ("python/bin/python3.11", 0o755, b"binary\n"),
                ("app/health_app.py", 0o644, b"app\n"),
            ):
                info = tarfile.TarInfo(name)
                info.mode = mode
                info.size = len(payload)
                archive.addfile(info, __import__("io").BytesIO(payload))

    def test_tar_keeps_start_script_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bundle.tar.gz"
            self.make_tar(path)
            modes = tar_modes(path)
            self.assertEqual(modes["start.sh"] & 0o777, 0o755)
            self.assertEqual(missing_exec_modes(modes, ["start.sh", "python/bin/python3.11"]), [])

    def test_tar_reports_a_missing_executable_bit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bundle.tar.gz"
            with tarfile.open(path, "w:gz") as archive:
                info = tarfile.TarInfo("start.sh")
                info.mode = 0o644
                info.size = 1
                archive.addfile(info, __import__("io").BytesIO(b"x"))
            modes = tar_modes(path)
            self.assertEqual(missing_exec_modes(modes, ["start.sh"]), ["start.sh"])


class TemplateTest(unittest.TestCase):
    VALUES = {
        "APP_ID": "app",
        "DISPLAY_NAME": "Example",
        "VERSION": "0.1.0",
        "BUNDLE_DIR": r"C:\work\bundle",
        "OUTPUT_DIR": r"C:\work\dist",
        "OUTPUT_NAME": "setup",
        "OUTPUT_FILE": r"C:\work\dist\setup.exe",
    }

    def test_iss_installs_per_user_below_localappdata(self) -> None:
        script = render_iss(self.VALUES)
        lowered = script.lower()
        self.assertIn("privilegesrequired=lowest", lowered)
        self.assertIn(r"defaultdirname={localappdata}\programs\app\0.1.0", lowered)
        self.assertIn("pythonw.exe", lowered)
        self.assertIn("launcher.py", lowered)

    def test_nsi_requests_user_level(self) -> None:
        script = render_nsi(self.VALUES)
        lowered = script.lower()
        self.assertIn("requestexecutionlevel user", lowered)
        self.assertIn("$localappdata\\programs\\app\\0.1.0", lowered)
        self.assertIn("pythonw.exe", lowered)
        self.assertIn("launcher.py", lowered)

    def test_template_rejects_an_unfilled_value(self) -> None:
        with self.assertRaises(HarnessError):
            render_iss({"APP_ID": "app"})


class WindowsCommandTest(unittest.TestCase):
    def test_installer_silent_flags_follow_the_tool(self) -> None:
        self.assertEqual(
            silent_flags("inno", Path("/work dir/install")),
            ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", '/DIR="/work dir/install"'],
        )
        self.assertEqual(
            silent_flags("nsis", Path("/work dir/install")),
            ["/S", "/D=/work dir/install"],
        )
        self.assertEqual(
            silent_flags("inno", None),
            ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
        )


class ResultTest(unittest.TestCase):
    def test_probe_keeps_a_thing_failure_as_a_result(self) -> None:
        probe = Probe()

        def fail() -> dict:
            raise ProbeError("server did not start")

        check = probe.check("app.health", fail)
        self.assertEqual(check.status, "fail")
        self.assertFalse(check.harness_error)
        self.assertFalse(probe.harness_failed)

    def test_probe_marks_a_harness_error(self) -> None:
        probe = Probe()

        def fail() -> dict:
            raise HarnessError("archive is unreadable")

        check = probe.check("archive.check", fail)
        self.assertEqual(check.status, "fail")
        self.assertTrue(check.harness_error)
        self.assertTrue(probe.harness_failed)

    def test_require_turns_a_false_condition_into_a_probe_error(self) -> None:
        with self.assertRaises(ProbeError):
            require(False, "not healthy")

    def test_summary_lists_measurements_and_checks(self) -> None:
        payload = {
            "os": "linux",
            "mode": "real",
            "python": {"version": "3.11.18", "asset": {"name": "runtime.tar.gz"}},
            "installer": {"tool": "tarball", "bytes": 10},
            "paths": {"install": "/srv/example/Programs/app/0.1.0"},
            "user": {"created": True, "login": "user"},
            "measurements": {
                "download_bytes": 1,
                "compressed_bytes": 2,
                "installed_bytes": 3,
                "install_seconds": 4.0,
                "start_seconds": 5.0,
            },
            "checks": [{"id": "app.health", "status": "pass", "detail": "ok"}],
        }
        text = summary_markdown(payload)
        self.assertIn("Installer probe on linux", text)
        self.assertIn("app.health", text)
        self.assertIn("start_seconds", text)
        self.assertIn("install dir", text)


class WindowsParsingTest(unittest.TestCase):
    def test_shortcut_parser_reads_three_fields(self) -> None:
        target, arguments, working = parse_shortcut(
            r"C:\install\python\pythonw.exe" + "\r\n" + r'"C:\install\launcher.py"' + "\r\n" + r"C:\install" + "\r\n"
        )
        self.assertTrue(target.endswith("pythonw.exe"))
        self.assertIn("launcher.py", arguments)
        self.assertEqual(working, r"C:\install")

    def test_shortcut_parser_rejects_short_output(self) -> None:
        with self.assertRaises(HarnessError):
            parse_shortcut("only one line")

    def test_task_parser_reads_status_and_last_result(self) -> None:
        status, result = parse_task_status("TaskName: probe\r\nStatus: Ready\r\nLast Result: 0\r\n")
        self.assertEqual(status, "Ready")
        self.assertEqual(result, 0)

    def test_task_parser_handles_not_run(self) -> None:
        status, result = parse_task_status("Status: Ready\r\nLast Result: 267011\r\n")
        self.assertEqual(status, "Ready")
        self.assertEqual(result, 267011)


class HealthTest(unittest.TestCase):
    def serve(self, status: int, payload: dict) -> tuple[HTTPServer, threading.Thread]:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - http.server API
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def test_health_accepts_ok_payload(self) -> None:
        server, thread = self.serve(200, {"status": "ok", "python": "/install/env/bin/python"})
        try:
            payload = wait_health(server.server_address[1], timeout=5.0)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
        self.assertEqual(payload["status"], "ok")

    def test_health_rejects_a_non_ok_payload(self) -> None:
        server, thread = self.serve(200, {"status": "bad"})
        try:
            with self.assertRaises(ProbeError):
                wait_health(server.server_address[1], timeout=1.0)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_port_file_reports_a_launcher_error(self) -> None:
        with self.assertRaises(ProbeError):
            parse_port_file(json.dumps({"error": "no health"}))
        record = parse_port_file(json.dumps({"port": 8712, "server_pid": 3}))
        self.assertEqual(record["port"], 8712)

    def test_port_file_rejects_broken_json(self) -> None:
        with self.assertRaises(ProbeError):
            parse_port_file("{")


if __name__ == "__main__":
    unittest.main()
