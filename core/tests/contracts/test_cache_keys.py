"""Cache keys use canonical JSON and reject floats."""

from __future__ import annotations

import pytest

from app.services.pipeline.cache_keys import API_VERSION, cache_key, canonical_json, speed_key


def test_canonical_json_sorts_keys_and_keeps_utf8() -> None:
    assert canonical_json({"b": 1, "a": "한"}) == '{"a":"한","b":1}'.encode()


def test_cache_key_ignores_key_order() -> None:
    first = cache_key(
        "tts_wav", {"text": "가", "voice": {"id": "fixed_wav", "revision": "0" * 64}}
    )
    second = cache_key(
        "tts_wav", {"voice": {"revision": "0" * 64, "id": "fixed_wav"}, "text": "가"}
    )
    assert first == second
    assert len(first) == 64


def test_cache_key_separates_kind_and_version() -> None:
    inputs = {"text": "가"}
    assert cache_key("tts_wav", inputs) != cache_key("timing_json", inputs)
    assert cache_key("tts_wav", inputs) != cache_key(
        "tts_wav", inputs, api_version=API_VERSION + 1
    )


def test_float_is_rejected() -> None:
    with pytest.raises(TypeError):
        cache_key("tts_wav", {"speed": 1.0})


def test_speed_key_is_a_two_decimal_string() -> None:
    assert speed_key(1.0) == "1.00"
    assert speed_key(0.8) == "0.80"
    assert speed_key(1.25) == "1.25"
    with pytest.raises(ValueError):
        speed_key(1.005)
    keyed = cache_key("tts_wav", {"speed": speed_key(1.0), "text": "가"})
    plain = cache_key("tts_wav", {"speed": "1", "text": "가"})
    assert keyed != plain


def test_non_string_key_is_rejected() -> None:
    with pytest.raises(TypeError):
        canonical_json({1: "x"})
