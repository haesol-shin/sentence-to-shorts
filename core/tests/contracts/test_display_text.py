"""Display text clusters and the silent rule shared by render, mix and cache."""

from __future__ import annotations

import unicodedata

from app.schemas.text import clusters, is_silent, voiced_clusters


def test_combining_mark_stays_with_its_base() -> None:
    text = unicodedata.normalize("NFD", "Á가")
    spans = clusters(text)
    assert [text[start:end] for start, end in spans] == [
        unicodedata.normalize("NFD", "Á"),
        unicodedata.normalize("NFD", "가"),
    ]


def test_emoji_zwj_sequence_is_one_cluster() -> None:
    assert clusters("👩\u200d💻") == [(0, 3)]


def test_regional_indicators_pair_into_one_cluster() -> None:
    assert clusters("🇰🇷🇺🇸") == [(0, 2), (2, 4)]


def test_variation_selector_stays_with_its_base() -> None:
    assert clusters("❤\ufe0f") == [(0, 2)]
    assert clusters("1\u20e3") == [(0, 2)]


def test_whitespace_and_punctuation_are_silent() -> None:
    for cluster in (" ", "\t", "!", "…", "("):
        assert is_silent(cluster), cluster
    for cluster in ("가", "A", "1", "❤\ufe0f"):
        assert not is_silent(cluster), cluster


def test_voiced_clusters_skip_spaces_and_punctuation() -> None:
    text = "타 자!"
    assert [(start, end) for start, end in voiced_clusters(text)] == [(0, 1), (2, 3)]
