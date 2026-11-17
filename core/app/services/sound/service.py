"""BGM selection, upload import and the video mix.

Scenes sit on the audio clock where their clips really start: a clip has a
whole number of frames, so a scene starts at the rounded time of the frames
before it. The BGM is decoded once, looped over the whole video with an
equal-power crossfade at every loop seam, and handed to the media mix as one
bed under the voice, where the sidechain ducking and the two-pass loudness
target apply.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import struct
import sys
import threading
import time
import wave
from array import array
from datetime import UTC, datetime
from pathlib import Path

from app.ports import (
    AppError,
    AppSettings,
    CatalogPort,
    JobContext,
    MediaPort,
    MixItem,
    MixPlan,
    ServiceDeps,
    UnknownCatalogId,
    UploadSource,
    canonical_digest,
    scene_starts_ms,
)
from app.schemas.artifact import Timing
from app.schemas.bgm_entry import (
    BgmEntry,
    BuiltinBgm,
    CodeBgm,
    ReviewStatus,
    SfxEntry,
    TypingSoundEntry,
    UploadBgm,
)
from app.schemas.common import PERSONAL_OWNER_ID, CaptionMode, LocalizedText, Mood, PinnedRef
from app.schemas.job import Job
from app.schemas.scene import CueAt, Scene
from app.schemas.settings import BgmSettings, Settings
from app.schemas.text import is_silent
from app.schemas.video import Video

SAMPLE_RATE = 44100
"""Internal audio rate (CONTRACTS 12)."""

CROSSFADE_MS = 500
"""Equal-power crossfade at each BGM loop seam, as the bundled-binary probe measured."""

END_FADE_MS = 500
"""BGM fade-out at the end of the video, so the last frame does not cut a note."""

DUCKING_DB_X10 = -120
"""Marks the BGM bed as ducked. The sidechain compressor of the media adapter sets the
depth; the probe measured about 17 dB under loud speech."""

SFX_GAIN_DB_X10 = -60
"""Sound effects sit under the voice: one key accent per scene, never louder than speech."""

TYPING_GAIN_MIN_DB_X10 = -50
"""Quietest typing key on the gain_db_x10 scale, -5.0 dB."""

TYPING_GAIN_MAX_DB_X10 = 0
"""Loudest typing key: never above the voice."""

MAX_BGM_MS = 600_000
"""Longest BGM file the mix decodes, the schema's duration limit."""

MIN_UPLOAD_MS = 500
"""Shortest accepted upload, the schema's duration floor."""

UPLOAD_LABEL = LocalizedText(ko="업로드한 BGM", en="Uploaded BGM")
"""Label of every upload; the original file name is never stored."""

UPLOAD_MOOD = Mood.calm
"""Mood of an upload until the user picks one; the upload request carries none."""

BGM_DIR = "bgm"
MIX_DIR = "mix"
UPLOAD_DIR = "upload"

_CROCKFORD32 = "0123456789abcdefghjkmnpqrstvwxyz"
_ID_LOCK = threading.Lock()
_LAST_ID_MS = 0


def _upload_id() -> str:
    """A fresh ``u_`` TypeID over a UUIDv7 (CONTRACTS 1.1), one per import job."""
    global _LAST_ID_MS
    with _ID_LOCK:
        now_ms = max(time.time_ns() // 1_000_000, _LAST_ID_MS + 1)
        _LAST_ID_MS = now_ms
    rand = int.from_bytes(secrets.token_bytes(10), "big")
    value = (now_ms & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76
    value |= (rand >> 68) & 0xFFF
    value |= 0b10 << 62
    value |= rand & ((1 << 62) - 1)
    body = "".join(_CROCKFORD32[(value >> (5 * index)) & 0x1F] for index in range(25, -1, -1))
    return f"u_{body}"


def loop_samples(source: array, total: int, crossfade: int) -> array:
    """``total`` mono float samples of the PCM16 ``source`` repeated without a gap.

    Each repeat overlaps the end of the previous one by ``crossfade`` samples
    (at most a quarter of the source) with equal-power gains, so a loop whose
    end does not meet its start leaves no step in the waveform. Samples are
    floats on the PCM16 full scale of 1.0 and are never clipped: equal-power
    gains on correlated material can reach about 1.41 times the source level,
    and only the media mix's loudness step brings the whole mix under its peak.
    """
    if not source:
        raise ValueError("an empty BGM cannot loop")
    scale = 1.0 / 32768
    unit = array("f", (value * scale for value in source))
    out = array("f", unit[:total])
    overlap = min(crossfade, len(unit) // 4)
    fade_out = [math.cos((index + 0.5) / overlap * math.pi / 2) for index in range(overlap)]
    fade_in = [math.sin((index + 0.5) / overlap * math.pi / 2) for index in range(overlap)]
    while len(out) < total:
        seam = len(out) - overlap
        for index in range(overlap):
            out[seam + index] = out[seam + index] * fade_out[index] + unit[index] * fade_in[index]
        out.extend(unit[overlap:])
    del out[total:]
    return out


def _fade_out(samples: array, length: int) -> None:
    length = min(length, len(samples))
    start = len(samples) - length
    for index in range(length):
        samples[start + index] = samples[start + index] * (length - index) / length


def _read_mono(path: Path) -> array:
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2 or handle.getnchannels() != 1:
            raise AppError("media_failed", detail={"step": "bgm_decode", "reason": "format"})
        samples = array("h")
        samples.frombytes(handle.readframes(handle.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def _write_float_mono(path: Path, samples: array) -> None:
    """A 32-bit float WAV (format 3), so values above full scale reach the mix intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = array("f", samples)
    if sys.byteorder != "little":
        data.byteswap()
    payload = data.tobytes()
    fmt = struct.pack("<HHIIHH", 3, 1, SAMPLE_RATE, SAMPLE_RATE * 4, 4, 32)
    with path.open("wb") as handle:
        handle.write(b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(payload)) + b"WAVE")
        handle.write(b"fmt " + struct.pack("<I", len(fmt)) + fmt)
        handle.write(b"data" + struct.pack("<I", len(payload)) + payload)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _typing_input(line_id: str, start_char: int, revision: str) -> dict[str, object]:
    return {"line_id": line_id, "start_char": start_char, "typing_sound": revision}


def typing_key_index(
    line_id: str,
    start_char: int,
    revision: str,
    key_count: int,
    previous: int | None,
) -> int:
    """Index of the key for one voiced span, never the same as the previous one.

    The index is the span digest modulo the candidate keys. A one-key sound
    repeats; a larger set removes the key used by the previous span of the line.
    """
    if key_count < 1:
        raise ValueError("a typing sound needs at least one key")
    if key_count == 1:
        return 0
    candidates = [index for index in range(key_count) if index != previous]
    digest = int(canonical_digest(_typing_input(line_id, start_char, revision)), 16)
    return candidates[digest % len(candidates)]


def typing_gain_db_x10(line_id: str, start_char: int, revision: str) -> int:
    """Deterministic key gain, an integer from -50 to 0."""
    digest = int(
        canonical_digest({**_typing_input(line_id, start_char, revision), "gain": True}),
        16,
    )
    span = TYPING_GAIN_MAX_DB_X10 - TYPING_GAIN_MIN_DB_X10 + 1
    return TYPING_GAIN_MIN_DB_X10 + digest % span


class SoundService:
    def __init__(
        self,
        media: MediaPort,
        catalog: CatalogPort,
        *,
        max_upload_bytes: int,
        max_upload_ms: int,
    ) -> None:
        self.media = media
        self.catalog = catalog
        self.max_upload_bytes = max_upload_bytes
        self.max_upload_ms = max_upload_ms

    def pick_bgm(
        self, settings: Settings, recent: list[str], seed: int
    ) -> PinnedRef:
        """A verified builtin BGM of the settings' mood, chosen by ``seed``.

        ``recent`` lists BGM ids from newest to oldest. Unused tracks come first;
        when every track of the mood was used, the least recently used ones
        remain. A mood without tracks falls back to every verified track.
        """
        mood = settings.audio.bgm.mood
        verified: list[BuiltinBgm] = []
        for item in self.catalog.list("bgm"):
            entry = self.catalog.get("bgm", item.id, item.revision)
            if isinstance(entry, BuiltinBgm) and entry.review_status == ReviewStatus.verified:
                verified.append(entry)
        candidates = [entry for entry in verified if entry.mood == mood] or verified
        if not candidates:
            raise AppError("unknown_catalog_id", detail={"kind": "bgm", "mood": mood.value})
        age = {item_id: index for index, item_id in reversed(list(enumerate(recent)))}
        oldest = max(age.get(entry.id, len(recent)) for entry in candidates)
        pool = sorted(
            entry.id for entry in candidates if age.get(entry.id, len(recent)) == oldest
        )
        index = int(canonical_digest({"mood": mood.value, "seed": seed}), 16) % len(pool)
        return self.catalog.pin("bgm", pool[index])

    def import_upload(
        self, src: Path, project_id: str, *, ctx: JobContext
    ) -> BgmEntry:
        """Convert an uploaded file to 44.1 kHz mono PCM16 WAV under a new upload id.

        The file opens only through the media adapter's fixed demuxer list. Too
        many bytes, too long, too short, or a file that does not decode fails
        with ``upload_invalid``. The WAV is named by the upload id; the original
        name is not read or stored.
        """
        ctx.cancel.raise_if_set()
        size = src.stat().st_size
        if size == 0:
            raise AppError("upload_invalid", detail={"reason": "empty"})
        if size > self.max_upload_bytes:
            raise AppError(
                "upload_invalid", detail={"reason": "too_large", "max_bytes": self.max_upload_bytes}
            )
        upload_id = _upload_id()
        out = ctx.job_dir / UPLOAD_DIR / f"{upload_id}.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            info = self.media.decode_audio(
                src,
                out=out,
                sample_rate=SAMPLE_RATE,
                channels=1,
                max_ms=self.max_upload_ms,
                cancel=ctx.cancel,
            )
        except AppError as error:
            out.unlink(missing_ok=True)
            if error.code == "media_too_long":
                raise AppError(
                    "upload_invalid", detail={"reason": "too_long", "max_ms": self.max_upload_ms}
                ) from error
            if error.code in ("media_unreadable", "media_failed"):
                raise AppError("upload_invalid", detail={"reason": "undecodable"}) from error
            raise
        duration_ms = info.duration_ms or 0
        if info.sample_rate != SAMPLE_RATE or info.channels != 1:
            out.unlink(missing_ok=True)
            raise AppError("upload_invalid", detail={"reason": "undecodable"})
        if duration_ms < MIN_UPLOAD_MS:
            out.unlink(missing_ok=True)
            raise AppError("upload_invalid", detail={"reason": "too_short"})
        return UploadBgm(
            schema_version=1,
            id=upload_id,
            label=UPLOAD_LABEL,
            mood=UPLOAD_MOOD,
            file=out.name,
            sha256=_sha256(out),
            duration_ms=duration_ms,
            sample_rate=SAMPLE_RATE,
            channels=1,
            loudness_lufs_x10=None,
            true_peak_dbtp_x10=None,
            source="upload",
            owner_id=PERSONAL_OWNER_ID,
            project_id=project_id,
            upload_id=upload_id,
            original_bytes=size,
            accepted_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def submit_upload(
        self, project_id: str, upload: UploadSource, idempotency_key: str | None
    ) -> Job:
        raise NotImplementedError

    def mix(
        self,
        video: Video,
        timings: list[Timing],
        tts: dict[str, Path],
        *,
        ctx: JobContext,
    ) -> Path:
        """Mix the video's audio to one WAV of the video length.

        ``timings`` follow ``scene_order``; ``tts`` maps line ids to their WAVs.
        Each line plays at its scene start plus its timing start. Sound effect
        cues play at their line's start or end plus the offset, kept inside the
        video. The BGM bed runs the whole video and is ducked under speech when
        the settings ask for it; the media mix then meets -16 LUFS and -1 dBTP.
        """
        ctx.cancel.raise_if_set()
        if [timing.scene_id for timing in timings] != list(video.scene_order):
            raise AppError("timing_mismatch", detail={"reason": "scene_order"})
        starts, total_ms = scene_starts_ms(timings)
        audio = video.settings.audio
        typing_ref = video.settings.caption.typing_sound
        typing = (
            self._typing_sound(typing_ref)
            if audio.sfx_enabled and typing_ref is not None
            else None
        )
        items: list[MixItem] = []
        for start, timing in zip(starts, timings, strict=True):
            scene = video.scenes[timing.scene_id]
            lines = {line.line_id: line for line in timing.lines}
            if list(lines) != [line.id for line in scene.lines]:
                raise AppError("timing_mismatch", detail={"scene_id": scene.id})
            for line in timing.lines:
                path = tts.get(line.line_id)
                if path is None:
                    raise AppError(
                        "tts_failed", detail={"reason": "tts_missing", "line_id": line.line_id}
                    )
                items.append(MixItem(path=path, start_ms=start + line.start_ms))
            if typing is not None and typing_ref is not None:
                self._typing_items(
                    items, scene, timing, start, typing, typing_ref.revision
                )
            if not audio.sfx_enabled or scene.visual is None:
                continue
            for cue in scene.visual.sfx:
                line = lines.get(cue.line_id)
                if line is None:
                    raise AppError("reveal_line_unknown", detail={"line_id": cue.line_id})
                entry, path = self._sfx(cue.sfx_id)
                at = start + (line.start_ms if cue.at == CueAt.start else line.end_ms)
                at = min(max(0, at + cue.offset_ms), max(0, total_ms - entry.duration_ms))
                items.append(MixItem(path=path, start_ms=at, gain_db_x10=SFX_GAIN_DB_X10))
        bed = self._bed(audio.bgm, total_ms, ctx)
        ducked = audio.bgm.enabled and audio.bgm.ducking
        items.insert(
            0,
            MixItem(
                path=bed,
                start_ms=0,
                gain_db_x10=audio.bgm.gain_db_x10 if audio.bgm.enabled else 0,
                ducking_db_x10=DUCKING_DB_X10 if ducked else 0,
            ),
        )
        out = ctx.job_dir / MIX_DIR / "mix.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        self.media.mix(
            MixPlan(items=items, duration_ms=total_ms), out=out, cancel=ctx.cancel
        )
        ctx.cancel.raise_if_set()
        return out

    def _typing_sound(self, ref: PinnedRef) -> tuple[TypingSoundEntry, Path]:
        try:
            entry = self.catalog.get("sfx", ref.id, ref.revision)
            root = self.catalog.package_dir("sfx", ref)
        except UnknownCatalogId as error:
            raise AppError(
                "unknown_catalog_id", detail={"kind": "sfx", "id": ref.id}
            ) from error
        if not isinstance(entry, TypingSoundEntry):
            raise AppError("unknown_catalog_id", detail={"kind": "sfx", "id": ref.id})
        return entry, root

    def _typing_items(
        self,
        items: list[MixItem],
        scene: Scene,
        timing: Timing,
        start_ms: int,
        typing: tuple[TypingSoundEntry, Path],
        revision: str,
    ) -> None:
        """One key at each voiced typewriter span start, on the scene clock."""
        entry, root = typing
        texts = {line.id: line.display_text for line in scene.lines}
        for line in timing.lines:
            if line.caption.mode_used is not CaptionMode.typewriter:
                continue
            text = texts[line.line_id]
            previous: int | None = None
            for phrase in line.caption.phrases:
                cluster = text[phrase.start_char:phrase.end_char]
                if is_silent(cluster):
                    continue
                index = typing_key_index(
                    line.line_id,
                    phrase.start_char,
                    revision,
                    len(entry.keys),
                    previous,
                )
                key = entry.keys[index]
                items.append(
                    MixItem(
                        path=root / key.file,
                        start_ms=start_ms + phrase.start_ms,
                        gain_db_x10=typing_gain_db_x10(
                            line.line_id, phrase.start_char, revision
                        ),
                    )
                )
                previous = index

    def _sfx(self, ref: PinnedRef) -> tuple[SfxEntry, Path]:
        try:
            entry = self.catalog.get("sfx", ref.id, ref.revision)
            root = self.catalog.package_dir("sfx", ref)
        except UnknownCatalogId as error:
            raise AppError("unknown_catalog_id", detail={"kind": "sfx", "id": ref.id}) from error
        if not isinstance(entry, SfxEntry):
            raise AppError("unknown_catalog_id", detail={"kind": "sfx", "id": ref.id})
        return entry, root / entry.file

    def _bed(self, bgm: BgmSettings, total_ms: int, ctx: JobContext) -> Path:
        """The BGM looped to ``total_ms``, or silence of that length when BGM is off."""
        total = total_ms * SAMPLE_RATE // 1000
        bed = ctx.job_dir / BGM_DIR / "bed.wav"
        if not bgm.enabled:
            _write_float_mono(bed, array("f", bytes(4 * total)))
            return bed
        if bgm.entry is None:
            raise AppError("bgm_unresolved", detail={"mood": bgm.mood.value})
        try:
            entry = self.catalog.get("bgm", bgm.entry.id, bgm.entry.revision)
            root = self.catalog.package_dir("bgm", bgm.entry)
        except UnknownCatalogId as error:
            raise AppError(
                "unknown_catalog_id", detail={"kind": "bgm", "id": bgm.entry.id}
            ) from error
        if not isinstance(entry, (BuiltinBgm, UploadBgm, CodeBgm)):
            raise AppError("unknown_catalog_id", detail={"kind": "bgm", "id": bgm.entry.id})
        decoded = ctx.job_dir / BGM_DIR / "source.wav"
        decoded.parent.mkdir(parents=True, exist_ok=True)
        self.media.decode_audio(
            root / entry.file,
            out=decoded,
            sample_rate=SAMPLE_RATE,
            channels=1,
            max_ms=MAX_BGM_MS,
            cancel=ctx.cancel,
        )
        ctx.cancel.raise_if_set()
        samples = loop_samples(_read_mono(decoded), total, CROSSFADE_MS * SAMPLE_RATE // 1000)
        _fade_out(samples, END_FADE_MS * SAMPLE_RATE // 1000)
        _write_float_mono(bed, samples)
        decoded.unlink(missing_ok=True)
        return bed


def create(settings: AppSettings, deps: ServiceDeps) -> SoundService:
    uploads = getattr(getattr(settings, "app", None), "uploads", None)
    if uploads is None:
        raise RuntimeError("the settings carry no upload limits")
    return SoundService(
        deps.media,
        deps.catalog,
        max_upload_bytes=uploads.bgm_max_bytes,
        max_upload_ms=uploads.bgm_max_ms,
    )


__all__ = [
    "SoundService",
    "create",
    "loop_samples",
    "typing_gain_db_x10",
    "typing_key_index",
]
