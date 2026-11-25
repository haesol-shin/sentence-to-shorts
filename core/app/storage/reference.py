"""Kept reference frames in the video's project folder.

The analysis deletes the source, the audio, the transcript and the frames it did
not keep. Up to four chosen frames stay under
``p/<project_id>/v/<video_id>/ref/<reference_id>/`` so a later style request can
send the same pictures again. They live in the project tree, so deleting the
project removes them, and replacing the reference removes its own folder.
"""

from __future__ import annotations

import re
import shutil

from app.schemas.video import MAX_REFERENCE_FRAMES, REFERENCE_FRAME_PATTERN
from app.storage.paths import Layout, write_atomic

_FRAME_NAME = "frame_{}.png"
_NAME = re.compile(REFERENCE_FRAME_PATTERN)


class FileReferenceFrames:
    """ReferenceFrameStore on the project tree."""

    def __init__(self, layout: Layout) -> None:
        self._layout = layout

    def put(
        self, project_id: str, video_id: str, reference_id: str, frames: list[bytes]
    ) -> list[str]:
        if len(frames) > MAX_REFERENCE_FRAMES:
            raise ValueError(f"at most {MAX_REFERENCE_FRAMES} reference frames are kept")
        folder = self._layout.reference_dir(project_id, video_id, reference_id)
        if folder.is_symlink():
            folder.unlink()
        elif folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        names: list[str] = []
        for index, data in enumerate(frames):
            name = _FRAME_NAME.format(index)
            write_atomic(folder / name, data)
            names.append(name)
        return names

    def get(
        self, project_id: str, video_id: str, reference_id: str, names: list[str]
    ) -> list[bytes]:
        folder = self._layout.reference_dir(project_id, video_id, reference_id)
        kept: list[bytes] = []
        for name in names:
            if not _NAME.fullmatch(name):
                continue
            try:
                kept.append((folder / name).read_bytes())
            except OSError:
                continue
        return kept

    def prune(self, project_id: str, video_id: str, keep: str | None) -> None:
        root = self._layout.reference_root(project_id, video_id)
        if root.is_symlink():
            root.unlink(missing_ok=True)
            return
        if not root.is_dir():
            return
        for folder in root.iterdir():
            if keep is not None and folder.name == keep:
                continue
            if folder.is_symlink():
                folder.unlink(missing_ok=True)
            else:
                shutil.rmtree(folder, ignore_errors=True)


__all__ = ["FileReferenceFrames"]
