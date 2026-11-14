"""Unit checks for the bundled-ffmpeg probe harness.

These run without imageio-ffmpeg and without an x86_64 runner. The stub-executable tests need
a POSIX shell, so they skip on Windows; the workflow runs them on the Linux job.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_probe  # noqa: E402
from probe_harness import (  # noqa: E402
    HarnessError,
    Probe,
    ProbeError,
    detect_license,
    parse_astats_rms,
    parse_duration,
    parse_frames,
    parse_input_streams,
    parse_loudnorm,
    parse_version,
    raw_rgb24,
    summary_markdown,
    write_result,
    write_tone_wav,
)

VERSION_TEXT = """\
ffmpeg version n9.0.2-17-g2a571b6068 Copyright (c) 2000-2026 the FFmpeg developers
built with gcc 16.2.0 (crosstool-NG 1.29.0.7_b1a94f6)
configuration: --prefix=/ffbuild/prefix --enable-gpl --enable-version3 --enable-libx264
libavutil      61.  1.102 / 61.  1.102
"""

STREAM_TEXT = """\
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'clip.mp4':
  Duration: 00:00:01.00, start: 0.000000, bitrate: 182 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive), 1080x1920, 30 fps, 30 tbr, 15360 tbn
  Stream #0:1[0x2](und): Audio: aac (LC), 44100 Hz, mono, fltp, 128 kb/s
Output #0, null, to 'pipe:':
  Stream #0:0(und): Video: wrapped_avframe, yuv420p(progressive), 1080x1920, 30 fps
frame=   30 fps=0.0 q=-1.0 Lsize=N/A time=00:00:01.00
"""

LOUDNORM_TEXT = """\
[Parsed_loudnorm_0 @ 0x1]
{
\t"input_i" : "-25.25",
\t"input_tp" : "-20.40",
\t"input_lra" : "0.00",
\t"input_thresh" : "-35.25",
\t"target_offset" : "-0.05"
}
[out#0/null @ 0x2] video:0KiB
[Parsed_loudnorm_1 @ 0x3]
{
\t"input_i" : "-16.05",
\t"input_tp" : "-11.16",
\t"input_lra" : "0.00",
\t"input_thresh" : "-26.05",
\t"target_offset" : "-0.05"
}
"""


def make_payload(checks: list[dict]) -> dict:
    failed = [check for check in checks if check["status"] != "pass"]
    broken = [check for check in checks if check.get("harness_error")]
    return {
        "probe": "bundled-ffmpeg",
        "schema": 1,
        "generated_at": "2026-01-01T00:00:00Z",
        "runner": {"os": "Linux", "arch": "X64", "machine": "x86_64"},
        "imageio_ffmpeg": {"distribution": "imageio-ffmpeg", "version": "0.8.1", "source": "test"},
        "binary": {
            "path": "/tmp/ffmpeg",
            "bytes": 1,
            "sha256": "0" * 64,
            "version": {"version": "9.0.2", "version_line": "ffmpeg version 9.0.2"},
            "license": {"spdx": "GPL-3.0-or-later"},
            "ffprobe": {"bundled": False, "system": True, "metadata_method": "ffmpeg -i"},
        },
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "harness_errors": len(broken),
        },
    }


class ParserTests(unittest.TestCase):
    def test_parse_version_reads_build_and_configuration(self) -> None:
        parsed = parse_version(VERSION_TEXT)
        self.assertEqual(parsed["version"], "n9.0.2-17-g2a571b6068")
        self.assertIn("crosstool-NG", parsed["build"])
        self.assertIn("--enable-libx264", parsed["configuration"])

    def test_detect_license_splits_gpl_and_lgpl(self) -> None:
        gpl = detect_license("--enable-gpl --enable-version3")
        self.assertEqual((gpl["family"], gpl["spdx"]), ("GPL", "GPL-3.0-or-later"))
        gpl2 = detect_license("--enable-gpl")
        self.assertEqual(gpl2["spdx"], "GPL-2.0-or-later")
        lgpl = detect_license("--enable-shared")
        self.assertEqual((lgpl["family"], lgpl["spdx"]), ("LGPL", "LGPL-2.1-or-later"))
        lgpl3 = detect_license("--enable-version3")
        self.assertEqual(lgpl3["spdx"], "LGPL-3.0-or-later")

    def test_parse_loudnorm_uses_the_last_json_block(self) -> None:
        parsed = parse_loudnorm(LOUDNORM_TEXT)
        self.assertEqual(parsed["input_i"], -16.05)
        self.assertEqual(parsed["input_tp"], -11.16)

    def test_parse_loudnorm_rejects_output_without_a_block(self) -> None:
        with self.assertRaises(HarnessError):
            parse_loudnorm("no measurement here")

    def test_parse_streams_reads_input_side_only(self) -> None:
        streams = parse_input_streams(STREAM_TEXT)
        self.assertEqual(len(streams), 2)
        video, audio = streams
        self.assertEqual(video["type"], "video")
        self.assertEqual((video["codec"], video["pix_fmt"]), ("h264", "yuv420p"))
        self.assertEqual((video["width"], video["height"], video["fps"]), (1080, 1920, 30.0))
        self.assertEqual((audio["codec"], audio["sample_rate"], audio["channels"]), ("aac", 44100, "mono"))

    def test_parse_duration_and_last_frame_count(self) -> None:
        self.assertEqual(parse_duration(STREAM_TEXT), 1.0)
        self.assertEqual(parse_frames(STREAM_TEXT), 30)
        self.assertIsNone(parse_duration("Duration: N/A, start: 0.0"))

    def test_parse_astats_takes_the_last_rms_level(self) -> None:
        text = "[astats] RMS level dB: -30.0\n[astats] RMS level dB: -19.830741\n"
        self.assertEqual(parse_astats_rms(text), -19.830741)
        self.assertEqual(parse_astats_rms("[astats] RMS level dB: -inf"), float("-inf"))
        self.assertIsNone(parse_astats_rms("[astats] no level"))


class SyntheticMediaTests(unittest.TestCase):
    def test_write_tone_wav_is_mono_16_bit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tone.wav"
            write_tone_wav(path, 0.1, sample_rate=8000)
            with wave.open(str(path), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 1)
                self.assertEqual(handle.getsampwidth(), 2)
                self.assertEqual(handle.getframerate(), 8000)
                self.assertEqual(handle.getnframes(), 800)

    def test_raw_rgb24_repeats_one_frame(self) -> None:
        data = raw_rgb24(2, width=4, height=3)
        frame = 4 * 3 * 3
        self.assertEqual(len(data), frame * 2)
        self.assertEqual(data[:frame], data[frame:])


class ProbeRecordTests(unittest.TestCase):
    def test_check_records_a_probe_failure_as_a_result(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            probe = Probe(Path("/bin/false"), Path(folder))
            result = probe.check("sample_check", lambda: (_ for _ in ()).throw(ProbeError("bad stream")))
            self.assertEqual(result.status, "fail")
            self.assertIn("bad stream", result.error)
            self.assertFalse(result.harness_error)
            self.assertEqual(len(probe.checks), 1)

    def test_check_marks_a_harness_error_as_a_harness_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            probe = Probe(Path("/bin/false"), Path(folder))

            def broken() -> dict:
                raise HarnessError("no measurement block")

            result = probe.check("sample_check", broken)
            self.assertEqual(result.status, "fail")
            self.assertTrue(result.harness_error)
            self.assertIn("no measurement block", result.error)

    def test_check_marks_an_unexpected_exception_as_a_harness_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            probe = Probe(Path("/bin/false"), Path(folder))

            def broken() -> dict:
                raise ValueError("parser bug")

            result = probe.check("sample_check", broken)
            self.assertEqual(result.status, "fail")
            self.assertTrue(result.harness_error)

    def test_check_records_measurements(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            probe = Probe(Path("/bin/false"), Path(folder))
            result = probe.check("sample_check", lambda: {"frames": 30}, detail="sample")
            self.assertEqual(result.status, "pass")
            self.assertEqual(result.measurements, {"frames": 30})
            self.assertEqual(result.detail, "sample")


class ResultWriterTests(unittest.TestCase):
    def test_write_result_writes_json_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "out"
            passed = {"id": "rgb24_stdin_h264", "status": "pass", "detail": "ok", "measurements": {}}
            failed = {"id": "decode_ogg", "status": "fail", "detail": "", "error": "no decoder"}
            result_path, summary_path = write_result(output, make_payload([passed, failed]))
            stored = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["summary"]["failed"], 1)
            summary = summary_path.read_text(encoding="utf-8")
            self.assertIn("1 of 2 checks failed", summary)
            self.assertIn("decode_ogg", summary)
            self.assertNotIn("harness error", summary)

    def test_summary_names_harness_errors(self) -> None:
        broken = {
            "id": "rgb24_stdin_h264",
            "status": "fail",
            "detail": "",
            "error": "ValueError: bug",
            "harness_error": True,
        }
        summary = summary_markdown(make_payload([broken]))
        self.assertIn("harness error", summary)


@unittest.skipUnless(os.name == "posix", "needs a POSIX shell stub")
class StubExecutableTests(unittest.TestCase):
    STUB = """\
#!/bin/sh
case " $* " in
  *" -version "*)
    echo "ffmpeg version stub-build Copyright (c) test"
    echo "built with a test compiler"
    echo "configuration: --enable-gpl --enable-version3"
    exit 0
    ;;
esac
echo "stub failure" >&2
exit 1
"""

    ZERO_STUB = """\
#!/bin/sh
case " $* " in
  *" -version "*)
    echo "ffmpeg version stub-build Copyright (c) test"
    echo "built with a test compiler"
    echo "configuration: --enable-gpl --enable-version3"
    exit 0
    ;;
esac
exit 0
"""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.stub = Path(self.folder.name) / "ffmpeg-stub"
        self.stub.write_text(self.STUB, encoding="utf-8")
        self.stub.chmod(self.stub.stat().st_mode | stat.S_IXUSR)
        self.zero_stub = Path(self.folder.name) / "ffmpeg-zero-stub"
        self.zero_stub.write_text(self.ZERO_STUB, encoding="utf-8")
        self.zero_stub.chmod(self.zero_stub.stat().st_mode | stat.S_IXUSR)

    def test_raw_returns_a_nonzero_command(self) -> None:
        probe = Probe(self.stub, Path(self.folder.name) / "work")
        completed = probe.raw(["-i", "missing"])
        self.assertFalse(completed.ok)
        self.assertIn("stub failure", completed.stderr)

    def test_probe_media_rejects_a_failed_null_decode(self) -> None:
        probe = Probe(self.stub, Path(self.folder.name) / "work")
        with self.assertRaises(ProbeError) as raised:
            probe.probe_media(Path("upload.mp3"))
        self.assertIn("null decode failed", str(raised.exception))
        self.assertIn("stub failure", str(raised.exception))

    def test_command_raises_with_the_stderr_tail(self) -> None:
        probe = Probe(self.stub, Path(self.folder.name) / "work")
        with self.assertRaises(ProbeError) as raised:
            probe.command(["-i", "missing"])
        self.assertIn("exited 1", str(raised.exception))
        self.assertIn("stub failure", str(raised.exception))

    def test_failed_checks_keep_the_probe_exit_successful(self) -> None:
        output = Path(self.folder.name) / "out"
        code = run_probe.main(["--ffmpeg", str(self.stub), "--output", str(output)])
        self.assertEqual(code, 0)
        stored = json.loads((output / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["summary"]["failed"], stored["summary"]["total"])
        self.assertEqual(stored["summary"]["harness_errors"], 0)
        self.assertTrue(all(check["status"] == "fail" for check in stored["checks"]))
        self.assertFalse((output / "failure.json").exists())

    def test_missing_executable_is_a_harness_error(self) -> None:
        output = Path(self.folder.name) / "out"
        code = run_probe.main(
            ["--ffmpeg", str(Path(self.folder.name) / "missing"), "--output", str(output)]
        )
        self.assertEqual(code, 2)
        self.assertTrue((output / "failure.json").exists())

    def test_existing_work_folder_survives_a_failed_start(self) -> None:
        parent = Path(self.folder.name) / "existing"
        parent.mkdir()
        marker = parent / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        output = Path(self.folder.name) / "out"
        code = run_probe.main(
            [
                "--ffmpeg",
                str(Path(self.folder.name) / "missing"),
                "--output",
                str(output),
                "--work-dir",
                str(parent),
                "--keep-work",
            ]
        )
        self.assertEqual(code, 2)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertEqual(len(list(parent.glob("run-*"))), 1)

    def test_cleanup_removes_only_the_run_folder(self) -> None:
        parent = Path(self.folder.name) / "existing"
        parent.mkdir()
        marker = parent / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        output = Path(self.folder.name) / "out"
        code = run_probe.main(
            [
                "--ffmpeg",
                str(Path(self.folder.name) / "missing"),
                "--output",
                str(output),
                "--work-dir",
                str(parent),
            ]
        )
        self.assertEqual(code, 2)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertEqual(list(parent.glob("run-*")), [])

    def test_unreadable_output_fails_the_workflow(self) -> None:
        output = Path(self.folder.name) / "out"
        code = run_probe.main(["--ffmpeg", str(self.zero_stub), "--output", str(output)])
        self.assertEqual(code, 2)
        stored = json.loads((output / "result.json").read_text(encoding="utf-8"))
        self.assertGreater(stored["summary"]["harness_errors"], 0)
        self.assertFalse((output / "failure.json").exists())


if __name__ == "__main__":
    unittest.main()
