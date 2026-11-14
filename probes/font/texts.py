"""Test strings for the caption probe.

Each case names the caption rule it is measured against: Korean lines count
grapheme clusters up to 14, English lines up to 28. Mixed text uses the
Korean limit because the stricter limit covers the same line.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import regex

LIMITS = {"ko": 14, "en": 28}


@dataclass(frozen=True)
class Case:
    case_id: str
    text: str
    rule: str
    intent: str
    alternate: str | None = None
    typewriter: bool = False

    @property
    def limit(self) -> int:
        return LIMITS[self.rule]


CASES: tuple[Case, ...] = (
    Case("ko_long", "오늘은 아주 긴 한국어 자막 문장을 한 줄에 넣어 봅니다", "ko", "긴 한글"),
    Case("en_identifier", "load_balancer_max_connections_per_worker", "en", "영문 식별자"),
    Case("digits", "1234567890 3.14 2^32 50%", "en", "숫자와 기호"),
    Case("paren", "결과(2026년 11월) 확인", "ko", "괄호"),
    Case("mixed", "API 응답 250ms (평균) 처리", "ko", "혼합 문자"),
    Case(
        "jamo",
        unicodedata.normalize("NFD", "각신"),
        "ko",
        "자모 분리",
        alternate=unicodedata.normalize("NFC", "각신"),
    ),
    Case("emoji", "설명 😀 끝", "ko", "이모지 하나"),
    Case("typewriter", "타자 효과: 각인 e\u0301 🇰🇷", "ko", "타자 효과용 grapheme 분할", typewriter=True),
)

CASE_BY_ID = {case.case_id: case for case in CASES}


def split_clusters(text: str) -> list[str]:
    """Split into grapheme clusters so a typed prefix never cuts a cluster."""
    return regex.findall(r"\X", text)


def describe(case: Case) -> dict:
    clusters = split_clusters(case.text)
    return {
        "case": case.case_id,
        "text": case.text,
        "rule": case.rule,
        "limit": case.limit,
        "intent": case.intent,
        "codepoints": len(case.text),
        "clusters": len(clusters),
        "cluster_list": clusters,
        "alternate": case.alternate,
    }
