"""The compute device the speech adapters load on, and when it may step down.

TTS and ASR share this table so one mode cannot drift from the other: `cpu`
forces the CPU, `cuda` probes and verifies a GPU and names an unusable one at
startup, and `auto` probes a GPU and may step down to the CPU once after a failed
load. Adapters only supply their probe and verification calls.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

Device = Literal["cpu", "cuda"]
DeviceReason = Literal["configured", "detected", "unavailable", "load_failed"]


@dataclass
class DeviceSelection:
    """The chosen device and whether one CPU retry is still allowed."""

    requested: str
    device: Device
    reason: DeviceReason
    stepped_down: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @classmethod
    def resolve(
        cls,
        requested: str,
        *,
        detect: Callable[[], bool],
        verify: Callable[[], str | None],
        verify_auto: bool,
        backend: str,
    ) -> "DeviceSelection":
        """Apply the mode table. `verify` returns None when the GPU is usable, else why not."""
        if requested == "cpu":
            return cls(requested, "cpu", "configured")
        if requested not in ("auto", "cuda"):
            raise RuntimeError("APP_DEVICE must be auto, cpu or cuda")
        detected = detect()
        if requested == "cuda":
            if not detected:
                raise RuntimeError(f"APP_DEVICE=cuda but {backend} cannot use a CUDA device")
            problem = verify()
            if problem is not None:
                raise RuntimeError(f"APP_DEVICE=cuda but {problem}")
            return cls(requested, "cuda", "configured")
        if not detected:
            return cls(requested, "cpu", "unavailable")
        if verify_auto:
            problem = verify()
            if problem is not None:
                return cls(requested, "cpu", "load_failed")
        return cls(requested, "cuda", "detected")

    @property
    def may_fall_back(self) -> bool:
        """Only an auto choice of CUDA may step down, and only once."""
        with self._lock:
            return self.requested == "auto" and self.device == "cuda" and not self.stepped_down

    def snapshot(self) -> tuple[Device, DeviceReason]:
        """Both fields from one state, so a status read never mixes two choices."""
        with self._lock:
            return self.device, self.reason

    def step_down(self) -> None:
        with self._lock:
            self.device = "cpu"
            self.reason = "load_failed"
            self.stepped_down = True


__all__ = ["Device", "DeviceReason", "DeviceSelection"]
