"""The smoke's voice phase and probe, run against fakes: no installer, no models, no torch."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
PACKAGING = REPO / "packaging"


def load_module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, PACKAGING / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


smoke = load_module("smoke")
probe = load_module("voice_probe")


class Clock:
    """Time only moves when the smoke sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


TIMING = {
    "lines": [
        {"line_id": "l1", "caption": {
            "mode_used": "phrase", "fallback_reason": None,
            "phrases": [{"start_char": 0, "end_char": 3, "start_ms": 0, "end_ms": 400}],
        }},
    ],
}


class FakeApi:
    """The routes the voice phase calls. The voice group is ready from `ready_at`."""

    def __init__(
        self, clock: Clock, *, ready_at: float = 20.0, early_start: bool = False,
        prepare_jobs: tuple[str, ...] = (), caption_mode: str = "phrase",
        already_ready: bool = False,
    ) -> None:
        self.clock = clock
        self.ready_at = 0.0 if already_ready else ready_at
        self.early_start = early_start
        self.prepare_jobs = prepare_jobs
        self.timing = json.loads(json.dumps(TIMING))
        self.timing["lines"][0]["caption"]["mode_used"] = caption_mode
        self.job_reads = 0
        self.pressed_at: float | None = None

    def group(self) -> dict[str, Any]:
        ready = self.clock.now >= self.ready_at
        return {
            "id": "voice", "state": "ready" if ready else "downloading",
            "done": 100 if ready else 40, "total": 100, "error_code": None, "retry_at": None,
        }

    def job(self) -> dict[str, Any]:
        assert self.pressed_at is not None
        self.job_reads += 1
        waiting = self.clock.now < self.ready_at and not self.early_start
        if waiting:
            state, queue = "queued", "queue"
        elif self.clock.now < self.ready_at + 2 and not self.early_start:
            state, queue = "running", None
        else:
            state, queue = ("succeeded" if self.clock.now >= self.ready_at + 4 else "running"), None
        done = state == "succeeded"
        return {
            "id": "j1", "state": state, "error": None,
            "progress": {"stage": None, "done": 0, "total": 0, "waiting_on": queue},
            "result": {"artifacts": {"final": "a_final", "timing": {"s1": "t1"}}} if done else None,
        }

    def get(self, path: str, params: Any = None) -> Any:
        if path == "/runtime":
            return {"prepare": {"groups": [self.group()]}}
        if path == "/jobs/j1":
            return self.job()
        if path == "/jobs":
            return {
                "items": [{"id": name, "kind": "runtime_prepare"} for name in self.prepare_jobs]
                + [{"id": "other", "kind": "generate"}],
                "next_cursor": None,
            }
        raise AssertionError(path)

    def post(self, path: str, body: Any = None, *, expect: int = 200) -> Any:
        assert path == "/videos/v1/generate" and expect == 202
        self.pressed_at = self.clock.now
        return {
            "id": "j1", "state": "queued", "error": None,
            "progress": {"stage": None, "done": 0, "total": 0, "waiting_on": "queue"},
            "result": None,
        }

    def download(self, path: str) -> bytes:
        if path == "/artifacts/t1":
            return json.dumps(self.timing).encode("utf-8")
        if path == "/videos/v1/download/mp4":
            return b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 40
        raise AssertionError(path)


class FakeLlm:
    def __init__(self, unmatched: list[str] | None = None) -> None:
        self.unmatched = unmatched or []
        self.served = ["draft/abc", "script/def"]


class Harness:
    """A VoicePlan whose processes are fakes. `stops` counts the app stops."""

    def __init__(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *,
        first_api: dict[str, Any] | None = None,
        second_api: dict[str, Any] | None = None, paired: bool = True,
        llm: FakeLlm | None = None, touch_models_on_second_stop: bool = False,
        report: dict[str, Any] | None = None,
    ) -> None:
        self.clock = Clock()
        self.models = tmp_path / "models"
        self.models.mkdir(parents=True)
        (self.models / "installed.json").write_text("{}", encoding="utf-8")
        (self.models / "m").mkdir()
        (self.models / "m" / "weights.bin").write_bytes(b"w" * 64)
        self.first_api = first_api or {}
        self.second_api = {"already_ready": True, **(second_api or {})}
        self.paired = paired
        self.touch = touch_models_on_second_stop
        self.starts: list[bool] = []
        self.stops = 0
        self.report = report or {
            "tts": {"ok": True, "detail": "2.1s of audio"},
            "align": {"ok": True, "detail": "5 timed phrases"},
            "torch": {"ok": True, "detail": "main 2.7.1+cpu, aligner 2.8.0+cpu"},
        }
        monkeypatch.setattr(
            smoke, "drive_to_scenes", lambda api: {"id": "v1", "revision": 3}
        )
        self.plan = smoke.VoicePlan(
            self.start, self.stop, lambda: self.report, self.models, llm or FakeLlm(),
            clock=self.clock, sleep=self.clock.sleep, poll_s=1.0, settle_s=0.0,
            generate_timeout_s=60.0,
        )

    def start(self, offline: bool) -> Any:
        self.starts.append(offline)
        options = self.second_api if offline else self.first_api
        run = smoke.Running(
            self.clock.now, first_page_s=2.5, health=200, page=200,
            api=FakeApi(self.clock, **options) if self.paired else None,
            problem=None if self.paired else "could not pair: no url",
        )
        return run

    def stop(self, run: Any) -> None:
        self.stops += 1
        if self.touch and len(self.starts) == 2:
            (self.models / "m" / "weights.bin").write_bytes(b"x" * 65)

    def run(self) -> Any:
        result = smoke.Result()
        smoke.voice_phase(result, self.plan)
        return result


def by_name(result: Any) -> dict[str, dict[str, Any]]:
    return {check["name"]: check for check in result.checks}


def test_21_voice_phase_reports_the_six_named_checks_all_gating_and_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    result = harness.run()
    checks = by_name(result)
    assert tuple(checks) == (
        smoke.CHECK_COLD, smoke.CHECK_GENERATE, smoke.CHECK_TTS, smoke.CHECK_ALIGN,
        smoke.CHECK_TORCH, smoke.CHECK_OFFLINE,
    )
    assert set(checks) == set(smoke.VOICE_CHECKS)
    assert [check["name"] for check in result.checks] == list(checks), "no check twice"
    assert all(check["ok"] and check["gating"] for check in checks.values()), result.checks
    assert harness.starts == [False, True] and harness.stops == 2
    assert result.seconds["first_page"] == 2.5
    assert result.seconds["voice_ready"] >= 20 and result.seconds["generate_wait"] >= 19
    assert result.sizes["models_bytes"] == 2 + 64
    assert "1 lines, 1 timed phrases" in checks[smoke.CHECK_GENERATE]["detail"]
    assert "draft/abc" in checks[smoke.CHECK_GENERATE]["detail"]
    assert not result.failed


def test_21_voice_names_are_the_six_the_release_expects() -> None:
    assert smoke.VOICE_CHECKS == (
        "cold start serves the page before preparation ends",
        "generate pressed during preparation waits and then succeeds",
        "second start downloads nothing without network",
        "TTS makes a wav from the installed files",
        "the installed aligner times the words of that wav",
        "the main and the aligner environments hold different torch",
    )


def test_21_voice_phase_fails_a_job_that_leaves_the_queue_before_the_voice_is_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(tmp_path, monkeypatch, first_api={"early_start": True})
    checks = by_name(harness.run())
    assert not checks[smoke.CHECK_GENERATE]["ok"]
    assert "left the queue while voice downloading" in checks[smoke.CHECK_GENERATE]["detail"]


def test_21_voice_phase_fails_when_the_voice_was_ready_before_generate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(tmp_path, monkeypatch, first_api={"already_ready": True})
    checks = by_name(harness.run())
    assert not checks[smoke.CHECK_COLD]["ok"], "ready is not a cold start"
    assert "nothing waited" in checks[smoke.CHECK_GENERATE]["detail"]


def test_21_voice_phase_stops_with_a_detail_at_the_generate_wait_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(tmp_path, monkeypatch, first_api={"ready_at": 10_000.0})
    checks = by_name(harness.run())
    detail = checks[smoke.CHECK_GENERATE]["detail"]
    assert not checks[smoke.CHECK_GENERATE]["ok"]
    assert "still queued after 60s" in detail and "voice downloading 40/100" in detail


def test_21_voice_phase_fails_generate_on_an_unmatched_llm_request_or_sentence_captions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    unmatched = Harness(tmp_path / "a", monkeypatch, llm=FakeLlm(["no recording matches: draft"]))
    checks = by_name(unmatched.run())
    assert not checks[smoke.CHECK_GENERATE]["ok"]
    assert "no recording matches: draft" in checks[smoke.CHECK_GENERATE]["detail"]
    sentence = Harness(tmp_path / "b", monkeypatch, first_api={"caption_mode": "sentence"})
    checks = by_name(sentence.run())
    assert not checks[smoke.CHECK_GENERATE]["ok"]
    assert "sentence captions" in checks[smoke.CHECK_GENERATE]["detail"]


def test_21_voice_phase_fails_the_offline_check_on_a_new_prepare_job_or_a_changed_model_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = Harness(tmp_path / "a", monkeypatch, second_api={"prepare_jobs": ("new",)})
    detail = by_name(job.run())[smoke.CHECK_OFFLINE]
    assert not detail["ok"] and "1 new runtime_prepare job" in detail["detail"]
    touched = Harness(tmp_path / "b", monkeypatch, touch_models_on_second_stop=True)
    detail = by_name(touched.run())[smoke.CHECK_OFFLINE]
    assert not detail["ok"] and "model file(s) changed" in detail["detail"]
    late = Harness(
        tmp_path / "c", monkeypatch, second_api={"already_ready": False, "ready_at": 1e9}
    )
    detail = by_name(late.run())[smoke.CHECK_OFFLINE]
    assert not detail["ok"] and "first /runtime shows voice downloading" in detail["detail"]


def test_21_voice_phase_names_all_six_checks_when_pairing_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(tmp_path, monkeypatch, paired=False)
    result = harness.run()
    checks = by_name(result)
    assert set(checks) == set(smoke.VOICE_CHECKS)
    cold = checks[smoke.CHECK_COLD]
    assert not cold["ok"] and "could not pair" in cold["detail"]
    assert checks[smoke.CHECK_GENERATE]["detail"].startswith("not run:")
    assert result.failed


def test_21_probe_report_maps_to_the_three_probe_check_names() -> None:
    result = smoke.Result()
    smoke.probe_checks(result, {
        "tts": {"ok": True, "detail": "2s"}, "align": {"ok": False, "detail": "0 phrases"},
        "torch": {"ok": True, "detail": "a b"},
    })
    assert [(c["name"], c["ok"]) for c in result.checks] == [
        (smoke.CHECK_TTS, True), (smoke.CHECK_ALIGN, False), (smoke.CHECK_TORCH, True),
    ]
    broken = smoke.Result()
    smoke.probe_checks(broken, {"error": "the probe exited 1 without a result"})
    assert [c["ok"] for c in broken.checks] == [False, False, False]
    assert all("without a result" in c["detail"] for c in broken.checks)


def test_21_runtime_verdict_wants_installer_items_ready_and_models_missing() -> None:
    good = {
        "deno": "ready", "ffmpeg": "ready", "package-qwen-tts": "ready",
        "model-asr-small": "missing", "model-align-ko": "missing",
    }
    ok, detail = smoke.runtime_verdict(good)
    assert ok and "package-qwen-tts" in detail and "model-align-ko" in detail
    assert not smoke.runtime_verdict({**good, "package-qwen-tts": "missing"})[0]
    ok, detail = smoke.runtime_verdict({**good, "model-asr-small": "ready"})
    assert not ok and "models already present: ['model-asr-small']" in detail
    assert not smoke.runtime_verdict({"ffmpeg": "ready"})[0], "a lock without models is wrong"
    assert not smoke.runtime_verdict({"model-asr-small": "missing"})[0], "ffmpeg is required"


def test_21_blocked_network_points_every_proxy_name_at_a_closed_port() -> None:
    env = smoke.blocked_network({"PATH": "x", "NO_PROXY": "*", "http_proxy": "http://real:1"})
    assert "NO_PROXY" not in env and env["PATH"] == "x"
    values = {env[name] for name in smoke.PROXY_NAMES}
    assert len(values) == 1
    port = int(values.pop().rsplit(":", 1)[1])
    import socket

    with socket.socket() as client, pytest.raises(OSError):
        client.settimeout(2)
        client.connect(("127.0.0.1", port))


def test_21_dev_gate_names_an_endpoint_and_the_other_profiles_do_not() -> None:
    env = {"HOME": "/h"}
    dev = smoke.gate_environment("dev", env)
    assert dev["HOME"] == "/h" and dev["APP_LLM_BASE_URL"].startswith("http://127.0.0.1:")
    assert smoke.gate_environment("release", env) == env


def test_21_failed_run_keeps_launcher_output_and_data_folder_logs(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "home" / "data" / "log").mkdir(parents=True)
    (work / "voice-data" / "log").mkdir(parents=True)
    (work / "dev.log").write_text("stdout", encoding="utf-8")
    (work / "home" / "data" / "log" / "launcher.log").write_text("cause", encoding="utf-8")
    (work / "voice-data" / "log" / "launcher.log.1").write_text("old", encoding="utf-8")
    (work / "voice-data" / "models.bin").write_text("skip", encoding="utf-8")
    kept = tmp_path / "kept"
    smoke.keep_logs(work, kept)
    assert {path.name: path.read_text(encoding="utf-8") for path in kept.iterdir()} == {
        "dev.log": "stdout",
        "home__data__log__launcher.log": "cause",
        "voice-data__log__launcher.log.1": "old",
    }


def test_21_size_and_snapshot_bookkeeping(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.bin").write_bytes(b"1" * 10)
    (tmp_path / "two.bin").write_bytes(b"2" * 5)
    assert smoke.tree_bytes(tmp_path) == 15
    assert smoke.tree_bytes(tmp_path / "missing") == 0
    before = smoke.snapshot_tree(tmp_path)
    assert set(before) == {"a/one.bin", "two.bin"}
    assert smoke.changed_files(before, smoke.snapshot_tree(tmp_path)) == []
    (tmp_path / "two.bin").write_bytes(b"3" * 6)
    (tmp_path / "new.bin").write_bytes(b"4")
    (tmp_path / "a" / "one.bin").unlink()
    assert smoke.changed_files(before, smoke.snapshot_tree(tmp_path)) == [
        "a/one.bin", "new.bin", "two.bin",
    ]


def test_21_pairing_hook_stores_the_url_the_launcher_opens(tmp_path: Path) -> None:
    native = "windows" if sys.platform == "win32" else "linux"
    script, url_file = smoke.write_pairing_hook(tmp_path, native)
    url = "http://127.0.0.1:8700/#pair=abc123"
    # A shell script needs no PATH; the batch file needs the Windows environment for cmd.
    env = dict(os.environ) if sys.platform == "win32" else {"PATH": ""}
    subprocess.run([str(script), url], check=True, env=env)
    assert smoke.read_pairing_code(url_file, 1.0) == "abc123"
    url_file.unlink()
    clock = Clock()
    with pytest.raises(smoke.SmokeError, match="pairing URL"):
        smoke.read_pairing_code(url_file, 1.0, clock=clock, sleep=clock.sleep)
    batch, _ = smoke.write_pairing_hook(tmp_path, "windows")
    assert "echo %*" in batch.read_text(encoding="utf-8")


def test_21_endpoint_model_ids_are_written_into_the_installed_config_only(tmp_path: Path) -> None:
    (tmp_path / "core" / "config").mkdir(parents=True)
    shipped = REPO / "core" / "config" / "models.yaml"
    target = tmp_path / "core" / "config" / "models.yaml"
    target.write_text(shipped.read_text(encoding="utf-8"), encoding="utf-8")
    smoke.give_endpoint_models(tmp_path)
    text = target.read_text(encoding="utf-8")
    assert 'openai_compat: ""' not in text and text.count('openai_compat: "recorded"') == 2
    assert 'openai_compat: ""' in shipped.read_text(encoding="utf-8")
    target.write_text("models: {}\n", encoding="utf-8")
    with pytest.raises(smoke.SmokeError):
        smoke.give_endpoint_models(tmp_path)


def test_21_word_timing_rejects_the_sentence_caption_fallback() -> None:
    clock = Clock()
    api = FakeApi(clock)
    job = {"result": {"artifacts": {"timing": {"s1": "t1"}}}}
    assert smoke.word_timing(api, job) == "1 lines, 1 timed phrases"
    api.timing["lines"][0]["caption"]["fallback_reason"] = "align_unavailable"
    with pytest.raises(smoke.SmokeError, match="align_unavailable"):
        smoke.word_timing(api, job)
    with pytest.raises(smoke.SmokeError, match="no timing artifact"):
        smoke.word_timing(api, {"result": {"artifacts": {}}})


def test_21_main_writes_sizes_and_seconds_next_to_the_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake(args: Any) -> Any:
        seen["voice"] = args.voice
        result = smoke.Result()
        result.check("one", True)
        result.sizes["artifact_bytes"] = 7
        result.seconds["first_page"] = 1.5
        return result

    monkeypatch.setattr(smoke, "smoke", fake)
    out = tmp_path / "out.json"
    code = smoke.main([
        "--artifact", str(tmp_path / "a.tar.gz"), "--os", "linux", "--profile", "release",
        "--voice", "--output", str(out),
    ])
    document = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0 and seen["voice"] is True
    assert document["sizes"] == {"artifact_bytes": 7} and document["seconds"] == {"first_page": 1.5}
    assert document["checks"][0]["name"] == "one"
    smoke.main(["--artifact", "x", "--os", "linux", "--profile", "dev"])
    assert seen["voice"] is False


def test_21_torch_part_needs_two_different_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    versions = {"main": "2.7.1+cpu", "aligner": "2.8.0+cpu"}
    monkeypatch.setattr(
        probe, "torch_version", lambda python, site, work, name: versions[name]
    )
    for name in ("APP_MAIN_SITE", "APP_ALIGN_SITE", "APP_ALIGN_PYTHON"):
        monkeypatch.setenv(name, name.lower())
    good = probe.probe_torch(tmp_path)
    assert good["ok"] and "2.7.1+cpu" in good["detail"] and "2.8.0+cpu" in good["detail"]
    versions["aligner"] = "2.7.1+cpu"
    assert not probe.probe_torch(tmp_path)["ok"]
    monkeypatch.delenv("APP_ALIGN_SITE")
    assert not probe.probe_torch(tmp_path)["ok"]


def test_21_probe_run_isolates_a_failed_part_and_skips_align_without_a_wav(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setattr(sys, "path", list(sys.path))

    def broken(root: Path, settings: Any, work: Path) -> Any:
        raise RuntimeError("model folder is empty")

    monkeypatch.setattr(probe, "probe_tts", broken)
    monkeypatch.setattr(probe, "probe_torch", lambda work: probe.part(True, "main a, aligner b"))
    report = probe.run(tmp_path)
    assert report["tts"] == {"ok": False, "detail": "RuntimeError: model folder is empty"}
    assert report["align"]["ok"] is False and "no wav" in report["align"]["detail"]
    assert report["torch"]["ok"] is True


def test_21_probe_cli_writes_the_report_file_and_exits_by_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "result.json"
    monkeypatch.setattr(probe, "run", lambda root: {"tts": probe.part(True, "ok")})
    assert probe.main(["--root", str(tmp_path), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {"tts": {"ok": True, "detail": "ok"}}
    monkeypatch.setattr(probe, "run", lambda root: {"tts": probe.part(False, "no")})
    assert probe.main(["--root", str(tmp_path), "--out", str(out)]) == 1
    assert os.path.exists(out)


class ScenesApi:
    """The routes `drive_to_scenes` calls; the caption mode starts as the app starts it."""

    def __init__(self, *, proposed: bool = False) -> None:
        self.mode = "sentence"
        self.revision = 1
        self.proposed = proposed
        self.changes: list[dict[str, Any]] = []

    def post(self, path: str, body: Any = None, *, expect: int = 200) -> Any:
        if path == "/projects":
            return {"id": "p1"}
        if path == "/projects/p1/videos":
            return {"id": "v1", "revision": self.revision}
        if path == "/videos/v1/draft" or path == "/videos/v1/previews":
            return {"id": "j", "state": "succeeded"}
        if path == "/videos/v1/changes":
            self.changes.append(body)
            if not self.proposed:
                self.mode = body["ops"][0]["value"]
            self.revision += 1
            return {"id": "c1", "status": "proposed" if self.proposed else "applied"}
        if path == "/changes/c1/apply":
            self.mode = self.changes[-1]["ops"][0]["value"]
            self.revision += 1
            return {}
        return {"id": "v1", "revision": self.revision}

    def get(self, path: str, params: Any = None) -> Any:
        assert path == "/videos/v1"
        return {"video": {"revision": self.revision, "settings": {"caption": {"mode": self.mode}}}}


@pytest.mark.parametrize("proposed", [False, True])
def test_21_the_scenes_are_driven_with_phrase_captions(proposed: bool) -> None:
    # The app starts in sentence captions, whose timing never carries phrases.
    api = ScenesApi(proposed=proposed)
    smoke.drive_to_scenes(api)  # type: ignore[arg-type]
    assert api.mode == "phrase"
    assert api.changes[0]["ops"] == [
        {"op": "set", "path": "/settings/caption/mode", "value": "phrase", "origin": "user"}
    ]


def test_result_check_prints_a_non_ascii_detail_when_the_console_is_cp1252(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", newline="\n", write_through=True)
    monkeypatch.setattr(sys, "stdout", console)
    monkeypatch.setattr(sys, "stderr", console)
    smoke.use_utf8_output()
    smoke.Result().check("install", True, "C:\\Users\\사용자\\앱")
    assert raw.getvalue().decode("utf-8") == "ok   install C:\\Users\\사용자\\앱\n"


def test_21_load_phases_of_the_launcher_log_are_printed_and_timed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "launcher.log"
    phase = "2026-01-01 00:00:01,000 INFO app.tools.tts.x.adapter tts load phase {} took {}s"
    log.write_text(
        "\n".join(
            [
                "2026-01-01 00:00:00,000 INFO launcher starting",
                phase.format("import_torch", "4.2"),
                phase.format("import_torch", "4.2"),
                phase.format("from_pretrained", "130.5"),
                "2026-01-01 00:09:00,000 WARNING app.tools.tts.x.adapter tts load timed out "
                "(phase limit, 300s in); last finished phase: from_pretrained",
            ]
        ),
        encoding="utf-8",
    )
    result = smoke.Result()
    smoke.report_load_phases(result, log)
    printed = capsys.readouterr().out.splitlines()
    assert len(printed) == 3 and "import_torch took 4.2s" in printed[0]
    assert "last finished phase: from_pretrained" in printed[2]
    assert result.seconds == {"tts_load_import_torch": 4.2, "tts_load_from_pretrained": 130.5}
    smoke.report_load_phases(result, tmp_path / "missing.log")
    assert "no TTS load line" in capsys.readouterr().out


def test_diagnosis_text_names_the_exit_status_stderr_and_import_timing() -> None:
    report = {
        "worker": {
            "ready": False, "timed_out": False, "returncode": 3221225477, "seconds": 4.2,
            "lines": [{"at": 1.5, "text": '{"type": "phase"}'}], "stderr_tail": "a\nb",
        },
        "import_torch": {
            "returncode": 0, "seconds": 9.1, "total_ms": 8000.0,
            "slowest": [{"module": "torch._C", "self_us": 5000, "cumulative_us": 6000}],
        },
    }
    lines = smoke.format_diagnosis(report)
    assert "worker exited 3221225477 before ready after 4.2s" in lines[0]
    assert any('+1.5s {"type": "phase"}' in line for line in lines)
    assert lines[lines.index("diagnosis: stderr tail:") + 2] == "diagnosis:   b"
    assert any("import torch exit 0, 9.1s wall" in line for line in lines)
    assert any("5.0ms own, 6.0ms with imports  torch._C" in line for line in lines)
    assert smoke.format_diagnosis({"error": "boom"}) == ["diagnosis: boom"]
    silent = {"worker": {"timed_out": True, "seconds": 600}, "import_torch": {"timed_out": True}}
    assert "still running at the limit" in smoke.format_diagnosis(silent)[0]


@pytest.mark.parametrize(
    ("generate", "tts", "expected"),
    [
        ("job failed: {'code': 'tts_timeout'}", "AppError: tts_timeout", True),
        ("job failed: {'code': 'tts_failed'}", "ok-ish", True),
        ("job failed: {'code': 'render_failed'}", "AppError: other", False),
    ],
)
def test_diagnosis_runs_only_after_a_tts_timeout_or_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, generate: str, tts: str, expected: bool,
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    calls: list[int] = []
    harness.plan.diagnose = lambda: calls.append(1) or ["diagnosis: worker"]
    monkeypatch.setattr(
        smoke, "check_generate", lambda result, plan, run: result.check(
            smoke.CHECK_GENERATE, False, generate)
    )
    harness.report["tts"] = {"ok": False, "detail": tts}
    harness.run()
    assert bool(calls) is expected


def test_diagnosis_is_not_run_when_the_voice_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.plan.diagnose = lambda: pytest.fail("no TTS failure, no diagnosis")
    assert not harness.run().failed


def test_diagnosis_environment_matches_what_the_launcher_gives_the_app(tmp_path: Path) -> None:
    from app.runtime.launcher import Distribution, apply_distribution

    dist = Distribution(
        profile="release", deployment="local", web_dir="web", profile_adapters={"release": {}},
    )
    expected: dict[str, str] = {}
    apply_distribution(tmp_path, dist, expected)
    given = smoke.diagnosis_environment(tmp_path, {"APP_MAIN_SITE": "kept elsewhere"})
    assert given["APP_RUNTIME_DIR"] == expected["APP_RUNTIME_DIR"]
    assert given["APP_MAIN_SITE"] == "kept elsewhere"
    assert smoke.diagnosis_environment(tmp_path, {})["APP_MAIN_SITE"] == expected["APP_MAIN_SITE"]


def test_diagnosis_driver_always_writes_a_report_file(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    done = subprocess.run(
        [sys.executable, "-c", smoke.DIAGNOSE_DRIVER, str(tmp_path), str(out)],
        cwd=REPO / "core", capture_output=True, check=False, timeout=120,
        env={**os.environ, "APP_MODEL_DIR": str(tmp_path / "models")},
    )
    assert done.returncode == 0, done.stderr.decode()
    report = json.loads(out.read_text(encoding="utf-8"))
    assert "error" in report or set(report) == {"worker", "import_torch"}
