"""The shared speech device table: modes, verification and the one CPU retry."""

from __future__ import annotations

import pytest

from app.tools.device import DeviceSelection


def _calls() -> tuple[list[str], object, object]:
    seen: list[str] = []

    def detect() -> bool:
        seen.append("detect")
        return True

    def verify() -> str | None:
        seen.append("verify")
        return None

    return seen, detect, verify


def test_device_cpu_does_not_probe_or_verify() -> None:
    seen, detect, verify = _calls()
    selection = DeviceSelection.resolve(
        "cpu", detect=detect, verify=verify, verify_auto=True, backend="test"
    )
    assert (selection.device, selection.reason) == ("cpu", "configured")
    assert seen == []


@pytest.mark.parametrize("verify_auto", [False, True])
def test_device_cuda_probes_and_verifies_before_start(verify_auto: bool) -> None:
    seen: list[str] = []

    def detect() -> bool:
        seen.append("detect")
        return True

    def verify() -> str | None:
        seen.append("verify")
        return "the gpu is broken"

    with pytest.raises(RuntimeError, match="the gpu is broken"):
        DeviceSelection.resolve(
            "cuda", detect=detect, verify=verify, verify_auto=verify_auto, backend="test"
        )
    assert seen == ["detect", "verify"]


def test_device_cuda_without_a_device_does_not_verify() -> None:
    seen: list[str] = []

    def detect() -> bool:
        seen.append("detect")
        return False

    def verify() -> str | None:
        seen.append("verify")
        return None

    with pytest.raises(RuntimeError, match="cannot use a CUDA device"):
        DeviceSelection.resolve(
            "cuda", detect=detect, verify=verify, verify_auto=True, backend="test"
        )
    assert seen == ["detect"]


@pytest.mark.parametrize(
    ("verify_auto", "verify_error", "expected"),
    [
        (False, "the gpu is broken", ("cuda", "detected")),
        (True, None, ("cuda", "detected")),
        (True, "the gpu is broken", ("cpu", "load_failed")),
    ],
)
def test_device_auto_applies_the_engine_verification_rule(
    verify_auto: bool, verify_error: str | None, expected: tuple[str, str]
) -> None:
    selection = DeviceSelection.resolve(
        "auto",
        detect=lambda: True,
        verify=lambda: verify_error,
        verify_auto=verify_auto,
        backend="test",
    )
    assert (selection.device, selection.reason) == expected


def test_device_auto_without_a_detected_device_stays_on_the_cpu() -> None:
    selection = DeviceSelection.resolve(
        "auto",
        detect=lambda: False,
        verify=lambda: None,
        verify_auto=True,
        backend="test",
    )
    assert (selection.device, selection.reason) == ("cpu", "unavailable")


def test_device_only_an_auto_cuda_choice_may_step_down_once() -> None:
    auto = DeviceSelection.resolve(
        "auto", detect=lambda: True, verify=lambda: None, verify_auto=False, backend="test"
    )
    assert auto.may_fall_back
    auto.step_down()
    assert (auto.device, auto.reason) == ("cpu", "load_failed")
    assert not auto.may_fall_back

    for requested in ("cpu", "cuda"):
        forced = DeviceSelection.resolve(
            requested, detect=lambda: True, verify=lambda: None, verify_auto=False, backend="test"
        )
        assert not forced.may_fall_back
