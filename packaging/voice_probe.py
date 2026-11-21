"""Run the installed voice stack once and write what it did to a JSON file.

    <bundled python> packaging/voice_probe.py --root <install folder> --out result.json

The release smoke runs this after the app made a video, with the bundled interpreter
(`pythonw.exe` on Windows, which has no console and no stdout, hence `--out`). It puts the
installed `core` and `site-packages` on the path like `launch.py`, fills the environment
exactly as the launcher does, and then uses the same adapters the app builds:

- `tts`: the Qwen adapter makes a wav of one Korean line from the installed package and
  the downloaded model.
- `align`: the installed aligner times the words of that wav; the result must carry word
  phrases and no failure.
- `torch`: the bundled interpreter imports torch once with the main environment only and
  once with the aligner environment only; the two versions must differ.

Each part reports `{"ok": bool, "detail": str}`; a failed part never hides the next one.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

LINE = "안녕하세요. 오늘은 커피 고르는 법을 알려 드릴게요."
VOICE_MANIFEST = Path("core") / "app" / "plugins" / "voices" / "sohee_ko" / "manifest.json"
TORCH_TIMEOUT_S = 600.0


class NeverCancelled:
    """A cancel token that is never set."""

    def is_set(self) -> bool:
        return False

    def raise_if_set(self) -> None:
        return None

    def wait(self, seconds: float) -> bool:
        time.sleep(seconds)
        return False


def part(ok: bool, detail: str) -> dict[str, Any]:
    return {"ok": bool(ok), "detail": detail}


def wav_facts(path: Path) -> tuple[float, bool]:
    """Seconds of audio and whether it holds any non-zero sample."""
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        data = handle.readframes(frames)
        return frames / handle.getframerate(), any(data)


def probe_tts(root: Path, settings: Any, work: Path) -> tuple[dict[str, Any], Path | None]:
    from app.schemas.voice_manifest import VoiceManifest
    from app.tools.tts.qwen3_tts_0_6b.adapter import create

    started = time.monotonic()
    voice = VoiceManifest.model_validate_json((root / VOICE_MANIFEST).read_text("utf-8"))
    adapter = create(settings)
    try:
        missing = adapter.ready()
        if missing:
            return part(False, f"the adapter reports missing: {missing}"), None
        made = adapter.synthesize(LINE, "ko", voice, out_dir=work, cancel=NeverCancelled())
    finally:
        adapter.close()
    seconds, audible = wav_facts(made.wav_path)
    took = time.monotonic() - started
    size = made.wav_path.stat().st_size
    detail = f"{seconds:.1f}s of audio, {size} bytes, made in {took:.0f}s"
    ok = audible and seconds > 0
    return part(ok, detail if audible else f"silent wav; {detail}"), made.wav_path


def probe_align(settings: Any, wav: Path | None) -> dict[str, Any]:
    if wav is None:
        return part(False, "no wav to align: the TTS part failed")
    from app.tools.align.adapter import create

    started = time.monotonic()
    aligner = create(settings)
    try:
        found = aligner.align(wav, LINE, LINE, "ko", cancel=NeverCancelled())
    finally:
        close = getattr(aligner, "close", None)
        if close is not None:
            close()
    took = time.monotonic() - started
    phrases = found.phrases or []
    ordered = all(a.start_ms <= b.start_ms for a, b in zip(phrases, phrases[1:], strict=False))
    ok = found.failure is None and bool(phrases) and ordered
    return part(ok, f"{len(phrases)} timed phrases, failure {found.failure}, in {took:.0f}s")


def torch_version(python: str, site: str, work: Path, name: str) -> str:
    """The torch version a clean interpreter sees with only `site` on its path."""
    out = work / f"torch-{name}.txt"
    env = {**os.environ, "PYTHONPATH": site, "PYTHONNOUSERSITE": "1"}
    code = "import sys, torch; open(sys.argv[1], 'w').write(torch.__version__)"
    done = subprocess.run(
        [python, "-c", code, str(out)], env=env, capture_output=True, check=False,
        timeout=TORCH_TIMEOUT_S,
    )
    if done.returncode != 0 or not out.is_file():
        tail = done.stderr.decode("utf-8", "replace").strip()[-200:]
        raise RuntimeError(f"{name} environment cannot import torch: {tail}")
    return out.read_text(encoding="utf-8").strip()


def probe_torch(work: Path) -> dict[str, Any]:
    main_site = os.environ.get("APP_MAIN_SITE")
    align_site = os.environ.get("APP_ALIGN_SITE")
    align_python = os.environ.get("APP_ALIGN_PYTHON")
    if not (main_site and align_site and align_python):
        return part(False, "the distribution environment does not name both site folders")
    main = torch_version(sys.executable, main_site, work, "main")
    aligner = torch_version(align_python, align_site, work, "aligner")
    return part(main != aligner, f"main {main}, aligner {aligner}")


def run(root: Path) -> dict[str, Any]:
    for name in ("core", "site-packages"):
        folder = root / name
        if folder.is_dir():
            sys.path.insert(0, str(folder))
    report: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="voice-probe-") as folder:
        work = Path(folder)
        wav: Path | None = None
        try:
            from app.runtime.launcher import apply_distribution, read_distribution
            from app.settings import Settings

            apply_distribution(root, read_distribution(root), os.environ)
            settings = Settings()
        except Exception as error:  # noqa: BLE001 - the report must say what broke
            message = f"{type(error).__name__}: {str(error)[:200]}"
            return {key: part(False, message) for key in ("tts", "align", "torch")}
        steps: list[tuple[str, Any]] = [
            ("tts", lambda: probe_tts(root, settings, work)),
            ("align", lambda: probe_align(settings, wav)),
            ("torch", lambda: probe_torch(work)),
        ]
        for key, step in steps:
            try:
                outcome = step()
            except Exception as error:  # noqa: BLE001
                outcome = part(False, f"{type(error).__name__}: {str(error)[:200]}")
            if key == "tts" and isinstance(outcome, tuple):
                outcome, wav = outcome
                if not outcome["ok"]:
                    wav = None
            report[key] = outcome
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(args.root.resolve())
    staged = args.out.with_name(args.out.name + ".tmp")
    staged.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    staged.replace(args.out)
    return 0 if all(entry["ok"] for entry in report.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
