"""Caption line breaking: the character rule against real glyph widths.

The character rule counts grapheme clusters. The pixel rule measures the
advance width the font reports for the text and breaks at a word boundary,
or inside a word that does not fit on a line of its own.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from texts import Case, split_clusters

SPACE = " "
Measure = Callable[[str], float]


def rule_lines(clusters: Sequence[str], limit: int) -> list[list[str]]:
    """Chunk clusters by count, which is what a character rule does."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    return [list(clusters[start : start + limit]) for start in range(0, len(clusters), limit)]


def words(clusters: Sequence[str]) -> list[list[str]]:
    """Split at spaces and drop the spaces; every word keeps its cluster order."""
    result: list[list[str]] = []
    current: list[str] = []
    for cluster in clusters:
        if cluster == SPACE:
            if current:
                result.append(current)
                current = []
        else:
            current.append(cluster)
    if current:
        result.append(current)
    return result


def pixel_lines(clusters: Sequence[str], box_width: float, measure: Measure) -> list[list[str]]:
    """Greedy wrap by measured width, with a hard break inside a long word."""
    lines: list[list[str]] = []
    line: list[str] = []
    for word in words(clusters):
        candidate = line + [SPACE] + word if line else list(word)
        if measure("".join(candidate)) <= box_width:
            line = candidate
            continue
        if line:
            lines.append(line)
            line = []
        rest = list(word)
        while rest:
            take = 0
            while take < len(rest) and measure("".join(rest[: take + 1])) <= box_width:
                take += 1
            if take == 0:
                take = 1
            line = rest[:take]
            rest = rest[take:]
            if rest:
                lines.append(line)
                line = []
    if line:
        lines.append(line)
    return lines


def as_text(lines: Sequence[Sequence[str]]) -> list[str]:
    """Join cluster lines into the strings a renderer draws."""
    return ["".join(line) for line in lines]


def normalized(text: str) -> str:
    """Collapse whitespace the way a caption renderer joins words."""
    return " ".join(text.split())


def compare(case: Case, measure: Measure, box_width: float, max_lines: int) -> dict:
    """Measure one case both ways and record where the rule disagrees."""
    clusters = split_clusters(case.text)
    counted = rule_lines(clusters, case.limit)
    measured = pixel_lines(clusters, box_width, measure)
    counted_text = [normalized("".join(line)) for line in counted]
    counted_widths = [round(measure(text), 2) for text in counted_text]
    measured_widths = [round(measure("".join(line)), 2) for line in measured]
    return {
        "case": case.case_id,
        "text": case.text,
        "rule": case.rule,
        "limit": case.limit,
        "clusters": len(clusters),
        "codepoints": len(case.text),
        "rule_line_count": len(counted),
        "rule_lines": counted_text,
        "rule_line_width_px": counted_widths,
        "rule_overflow": any(width > box_width for width in counted_widths),
        "pixel_line_count": len(measured),
        "pixel_line_width_px": measured_widths,
        "pixel_max_width_px": max(measured_widths, default=0.0),
        "pixel_lines": ["".join(line) for line in measured],
        "agrees": len(counted) == len(measured),
        "fits": len(measured) <= max_lines,
    }
