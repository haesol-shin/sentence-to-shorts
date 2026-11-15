#!/usr/bin/env python3
"""Render local before/after prompt responses as one static HTML page.

This tool reads only local response files. It never calls a model, a provider
SDK or the network. Run it manually when reviewing prompt style; keep the
page in a local output folder. The page is not application logging, and this
tool is not wired into CI.

Input format
------------
Use two UTF-8 files: ``--before`` (optional) and ``--after``. Each file is
either ``.json`` (one object or an array of objects) or ``.jsonl`` (one object
per non-empty line). One object describes one fixture response::

    {"fixture_id": "case-001",
     "input": "synthetic input text",
     "route": "script.default",
     "prompt_id": "prompt revision or digest",
     "provider": "anthropic_api",
     "model": "actual-model-id",
     "effort": "medium",
     "output_limit": 1200,
     "status": "ok",
     "text": "response text",
     "synthetic": true}

``status`` is ``ok``, ``failed`` or ``missing``. ``status`` ``ok`` requires a
non-empty ``text``. ``status`` ``failed`` requires ``error_code``. ``status``
``missing`` means that no result was produced. A fixture that appears in only
one file is shown with the other side marked missing.

``synthetic`` is optional. Use ``true`` for renderer proof data and ``false``
for a real model response to a synthetic input. Omitting it leaves provenance
unknown. Synthetic responses and unknown provenance are not style evidence.

Conditions that must match for a fair comparison are route, provider, actual
model ID, effort and output limit. The renderer also compares the input and
shows whether the before/after prompt identity changed. Differences are shown
next to the aligned fixture instead of being hidden.

Example::

    python scripts/compare_prompt_style.py \\
        --before before.jsonl --after after.jsonl --output page.html

The renderer never writes to an input file.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STATUSES = ("ok", "failed", "missing")
SAME_FIELDS = (
    ("route", "route"),
    ("provider", "provider"),
    ("model", "모델 ID"),
    ("effort", "effort"),
    ("output_limit", "출력 한도"),
)


class InputError(Exception):
    """A local input file or response record is not usable."""


@dataclass(frozen=True)
class Record:
    fixture_id: str
    input: str
    route: str
    prompt_id: str
    provider: str
    model: str
    effort: str | None
    output_limit: int
    status: str
    text: str | None
    error_code: str | None
    synthetic: bool | None


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _required_string(item: dict[str, Any], key: str, where: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{where}: {key} must be a non-empty string")
    return value


def _optional_string(item: dict[str, Any], key: str, where: str) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{where}: {key} must be a non-empty string or null")
    return value


def _record_from(item: dict[str, Any], role: str, where: str) -> Record:
    variant = item.get("variant")
    if variant is not None and variant != role:
        raise InputError(f"{where}: variant must be {role!r} for this input")
    status = item.get("status")
    if status not in STATUSES:
        raise InputError(f"{where}: status must be one of {', '.join(STATUSES)}")
    output_limit = item.get("output_limit")
    if (
        not isinstance(output_limit, int)
        or isinstance(output_limit, bool)
        or output_limit < 0
    ):
        raise InputError(f"{where}: output_limit must be a non-negative integer")
    synthetic = item.get("synthetic")
    if synthetic is not None and not isinstance(synthetic, bool):
        raise InputError(f"{where}: synthetic must be true, false or omitted")
    text = item.get("text")
    if text is not None and not isinstance(text, str):
        raise InputError(f"{where}: text must be a string or null")
    error_code = _optional_string(item, "error_code", where)
    if status == "ok" and (not isinstance(text, str) or not text.strip()):
        raise InputError(f"{where}: status ok requires non-empty text")
    if status == "failed" and error_code is None:
        raise InputError(f"{where}: status failed requires error_code")
    return Record(
        fixture_id=_required_string(item, "fixture_id", where),
        input=_required_string(item, "input", where),
        route=_required_string(item, "route", where),
        prompt_id=_required_string(item, "prompt_id", where),
        provider=_required_string(item, "provider", where),
        model=_required_string(item, "model", where),
        effort=_optional_string(item, "effort", where),
        output_limit=output_limit,
        status=status,
        text=text if status == "ok" else None,
        error_code=error_code if status == "failed" else None,
        synthetic=synthetic,
    )


def _parse_file(path: Path) -> list[tuple[Any, str]]:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise InputError(f"cannot read {path.name}: {exc}") from None
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        items: list[tuple[Any, str]] = []
        for number, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except (ValueError, TypeError):
                raise InputError(f"{path.name}:{number}: invalid JSON") from None
            items.append((value, f"{path.name}:{number}"))
        return items
    if suffix == ".json":
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            raise InputError(f"{path.name}: invalid JSON") from None
        if isinstance(value, list):
            return [
                (item, f"{path.name}[{index}]")
                for index, item in enumerate(value)
            ]
        return [(value, path.name)]
    raise InputError(f"{path.name}: input must be a .json or .jsonl file")


def _load_side(path: Path | None, role: str) -> dict[str, Record]:
    if path is None:
        return {}
    if not path.is_file():
        raise InputError(f"--{role} is not a local file: {path.name}")
    records: dict[str, Record] = {}
    for item, where in _parse_file(path):
        if not isinstance(item, dict):
            raise InputError(f"{where}: each record must be a JSON object")
        record = _record_from(item, role, where)
        if record.fixture_id in records:
            raise InputError(
                f"{where}: duplicate fixture_id {record.fixture_id!r}"
            )
        records[record.fixture_id] = record
    return records


def _condition_rows(before: Record | None, after: Record | None) -> list[tuple[str, Any, Any, str, str]]:
    rows: list[tuple[str, Any, Any, str, str]] = []
    if before is None or after is None:
        state = "비교 불가"
        rows.append(("prompt 구분값", None, None, state, "warn"))
    elif before.prompt_id == after.prompt_id:
        rows.append(
            ("prompt 구분값", before.prompt_id, after.prompt_id, "같음(확인 필요)", "warn")
        )
    else:
        rows.append(
            ("prompt 구분값", before.prompt_id, after.prompt_id, "변경됨", "ok")
        )
    for attribute, label in SAME_FIELDS:
        before_value = getattr(before, attribute) if before is not None else None
        after_value = getattr(after, attribute) if after is not None else None
        if before is None or after is None:
            state, css = "비교 불가", "warn"
        elif before_value == after_value:
            state, css = "같음", "ok"
        else:
            state, css = "다름", "diff"
        rows.append((label, before_value, after_value, state, css))
    return rows


def _input_state(before: Record | None, after: Record | None) -> tuple[str, str]:
    if before is None or after is None:
        return "비교 불가", "warn"
    if before.input == after.input:
        return "같음", "ok"
    return "다름", "diff"


def _condition_difference_count(before: Record | None, after: Record | None) -> int:
    if before is None or after is None:
        return 0
    count = sum(
        getattr(before, attribute) != getattr(after, attribute)
        for attribute, _label in SAME_FIELDS
    )
    if before.prompt_id == after.prompt_id:
        count += 1
    if before.input != after.input:
        count += 1
    return count


def _display_value(value: Any, css: str) -> str:
    if value is None:
        return '<span class="absent">없음</span>'
    return f'<code class="{css}">{_escape(value)}</code>'


def _badge(text: str, css: str) -> str:
    return f'<span class="badge {css}">{_escape(text)}</span>'


def _status_text(record: Record) -> str:
    if record.status == "ok":
        return "성공"
    if record.status == "failed":
        return f"실패: {_text(record.error_code) or '원인 없음'}"
    return "응답 누락"


def _synthetic_text(record: Record) -> str:
    if record.synthetic is True:
        return "합성 응답 (renderer 검증용)"
    if record.synthetic is False:
        return "실제 모델 응답으로 표시됨"
    return "합성 여부 미표시"


def _quality(before: Record | None, after: Record | None, *, before_provided: bool) -> tuple[str, str]:
    if not before_provided:
        return "unverified", "최초 작성: 변경 전 응답이 없어 문체 품질 미검증"
    if before is None or after is None:
        return "unverified", "전후 기록 중 하나가 없어 문체 품질 미검증"
    if before.status != "ok" or after.status != "ok":
        return "unverified", "전후 성공 응답이 모두 있어야 문체 품질을 검토할 수 있습니다"
    differences = [
        label
        for attribute, label in SAME_FIELDS
        if getattr(before, attribute) != getattr(after, attribute)
    ]
    if before.input != after.input:
        differences.append("입력")
    if differences:
        return (
            "check",
            f"조건이 다릅니다({', '.join(differences)}): "
            "문체 품질 비교 전에 조건 표의 차이를 확인하세요",
        )
    if before.prompt_id == after.prompt_id:
        return "check", "전후 prompt 구분값이 같습니다. 변경 전후 비교인지 확인하세요"
    if before.synthetic is True or after.synthetic is True:
        return "synthetic", "합성 응답: renderer 동작 검증용이며 문체 품질 증거가 아닙니다"
    if before.synthetic is None or after.synthetic is None:
        return "unverified", "합성 여부가 표시되지 않아 실제 문체 품질 미검증"
    return "reviewable", "입력에 실제 모델 응답으로 표시됨: 문체 품질은 검토자가 판단합니다"


def _render_side(record: Record | None, label: str, missing: str) -> str:
    if record is None:
        return (
            '<article class="side missing">'
            f"<h3>{_escape(label)}</h3>"
            f'<p class="state">{_escape(missing)}</p>'
            "</article>"
        )
    parts = [
        f'<article class="side {record.status}">',
        f"<h3>{_escape(label)}</h3>",
        '<dl class="meta">',
        f'<div><dt>route</dt><dd>{_escape(record.route)}</dd></div>',
        f'<div><dt>prompt</dt><dd><code>{_escape(record.prompt_id)}</code></dd></div>',
        f'<div><dt>provider</dt><dd>{_escape(record.provider)}</dd></div>',
        f'<div><dt>모델 ID</dt><dd><code>{_escape(record.model)}</code></dd></div>',
        f'<div><dt>effort</dt><dd>{_escape(record.effort or "없음")}</dd></div>',
        f'<div><dt>출력 한도</dt><dd>{_escape(record.output_limit)}</dd></div>',
        "</dl>",
        f'<p class="state">{_badge(_status_text(record), "status-" + record.status)}</p>',
        "<h4>입력</h4>",
        f'<pre class="input">{_escape(record.input)}</pre>',
        "<h4>응답</h4>",
    ]
    if record.status == "ok":
        parts.append(f'<pre class="response">{_escape(record.text or "")}</pre>')
    elif record.status == "failed":
        parts.append(
            f'<p class="failure">실패: {_escape(record.error_code or "원인 없음")}</p>'
        )
    else:
        parts.append('<p class="missing-state">응답 누락</p>')
    parts.append(f'<p class="synthetic">{_escape(_synthetic_text(record))}</p>')
    parts.append("</article>")
    return "\n".join(parts)


def _render_conditions(before: Record | None, after: Record | None) -> str:
    rows = [
        "<table class=\"conditions\">",
        "<thead><tr><th>조건</th><th>변경 전</th><th>변경 후</th><th>비교</th></tr></thead>",
        "<tbody>",
    ]
    for label, before_value, after_value, state, css in _condition_rows(before, after):
        rows.append(
            "<tr>"
            f"<th>{_escape(label)}</th>"
            f"<td>{_display_value(before_value, 'before-value')}</td>"
            f"<td>{_display_value(after_value, 'after-value')}</td>"
            f'<td><span class="condition {css}">{_escape(state)}</span></td>'
            "</tr>"
        )
    input_state, input_css = _input_state(before, after)
    rows.append(
        "<tr>"
        "<th>입력</th>"
        '<td colspan="2">좌우 입력 칸에서 비교</td>'
        f'<td><span class="condition {input_css}">{_escape(input_state)}</span></td>'
        "</tr>"
    )
    rows.extend(("</tbody>", "</table>"))
    return "\n".join(rows)


def _render_fixture(
    index: int,
    before: Record | None,
    after: Record | None,
    *,
    before_provided: bool,
) -> str:
    record = after if after is not None else before
    assert record is not None
    quality_class, quality_text = _quality(before, after, before_provided=before_provided)
    missing_before = "변경 전 응답 없음 (최초 작성)" if not before_provided else "변경 전 기록 없음"
    return "\n".join(
        [
            f'<section class="fixture" id="fixture-{index}">',
            f"<h2>{_escape(record.fixture_id)}</h2>",
            f'<p class="quality {quality_class}">{_escape(quality_text)}</p>',
            _render_conditions(before, after),
            '<div class="columns">',
            _render_side(before, "변경 전", missing_before),
            _render_side(after, "변경 후", "변경 후 기록 없음"),
            "</div>",
            "</section>",
        ]
    )


def _evidence_banner(records: list[Record]) -> tuple[str, str]:
    flags = {record.synthetic for record in records if record.status == "ok"}
    if True in flags:
        return (
            "synthetic",
            "합성 응답 포함: 이 페이지는 renderer 동작 검증용입니다. "
            "실제 prompt 문체 품질의 증거가 아닙니다.",
        )
    if None in flags or not flags:
        return (
            "unverified",
            "합성 여부가 표시되지 않은 응답이 있거나 성공 응답이 없습니다. "
            "실제 모델 출력인지 확인할 수 없어 문체 품질 미검증입니다.",
        )
    return (
        "reviewable",
        "입력에 실제 모델 응답으로 표시되어 있습니다. 이 페이지는 문체 품질을 "
        "자동 판정하지 않으며 검토자가 말투, 어휘, 읽기 자연스러움을 확인합니다.",
    )


def render_page(
    before: dict[str, Record],
    after: dict[str, Record],
    *,
    before_provided: bool,
) -> str:
    ids = list(after)
    ids.extend(fixture_id for fixture_id in before if fixture_id not in after)
    records = [*before.values(), *after.values()]
    banner_class, banner_text = _evidence_banner(records)
    differences = sum(
        _condition_difference_count(before.get(fixture_id), after.get(fixture_id))
        for fixture_id in ids
    )
    ok_pairs = sum(
        1
        for fixture_id in ids
        if before.get(fixture_id) is not None
        and after.get(fixture_id) is not None
        and before[fixture_id].status == "ok"
        and after[fixture_id].status == "ok"
    )
    failed = sum(record.status == "failed" for record in records)
    missing = sum(record.status == "missing" for record in records)
    absent_sides = sum(
        1
        for fixture_id in ids
        if before.get(fixture_id) is None or after.get(fixture_id) is None
    )
    sections = [
        _render_fixture(
            index,
            before.get(fixture_id),
            after.get(fixture_id),
            before_provided=before_provided,
        )
        for index, fixture_id in enumerate(ids, 1)
    ]
    summary = (
        f"fixture {len(ids)}개 · 조건 차이/확인 {differences}개 · "
        f"전후 모두 성공 {ok_pairs}개 · 실패 {failed}개 · 누락 {missing}개 · "
        f"한쪽 기록 없음 {absent_sides}개"
    )
    head = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prompt 문체 비교</title>
<style>
:root { color-scheme: light; --line: #d6d9de; --ink: #1d232b; --muted: #5b6470; }
* { box-sizing: border-box; }
body { margin: 0; background: #f6f7f9; color: var(--ink); font: 15px/1.6 system-ui, -apple-system, "Noto Sans KR", sans-serif; }
header, main, footer { max-width: 1500px; margin: 0 auto; padding: 0 1.25rem; }
header { padding-top: 2rem; padding-bottom: .5rem; }
h1 { margin: 0 0 .4rem; font-size: 1.65rem; }
h2 { margin: 0 0 .6rem; font-size: 1.2rem; overflow-wrap: anywhere; }
h3 { margin: 0 0 .7rem; font-size: 1rem; }
h4 { margin: 1rem 0 .35rem; font-size: .86rem; color: var(--muted); }
p { margin: .45rem 0; }
.lede { color: var(--muted); }
.banner { padding: .7rem .9rem; border: 1px solid var(--line); border-left-width: 5px; border-radius: .45rem; background: #fff; }
.banner.synthetic { border-left-color: #b45309; background: #fff7ed; }
.banner.unverified, .banner.check { border-left-color: #a16207; background: #fefce8; }
.banner.reviewable { border-left-color: #15803d; background: #f0fdf4; }
.summary { color: var(--muted); font-size: .9rem; }
.fixture { margin: 1.4rem 0 2rem; padding: 1rem; border: 1px solid var(--line); border-radius: .6rem; background: #fff; }
.quality { padding: .55rem .75rem; border-radius: .4rem; font-size: .9rem; }
.quality.synthetic { background: #fff7ed; color: #7c2d12; }
.quality.unverified, .quality.check { background: #fefce8; color: #713f12; }
.quality.reviewable { background: #f0fdf4; color: #14532d; }
.conditions { width: 100%; border-collapse: collapse; margin: .8rem 0 1rem; font-size: .87rem; }
.conditions th, .conditions td { padding: .35rem .45rem; border-bottom: 1px solid #eceef1; text-align: left; vertical-align: top; }
.conditions thead th { color: var(--muted); font-weight: 600; }
.conditions tbody th { width: 9rem; }
code { overflow-wrap: anywhere; }
.condition { display: inline-block; padding: .1rem .4rem; border-radius: .3rem; font-size: .82rem; }
.condition.ok { background: #dcfce7; color: #14532d; }
.condition.diff { background: #fee2e2; color: #7f1d1d; }
.condition.warn { background: #fef3c7; color: #713f12; }
.absent { color: var(--muted); }
.columns { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 1rem; }
.side { min-width: 0; padding: .85rem; border: 1px solid var(--line); border-radius: .5rem; }
.side.failed { border-left: 5px solid #b91c1c; }
.side.missing { border-style: dashed; color: var(--muted); }
.side.missing .state { color: var(--muted); }
.meta { margin: 0; display: grid; gap: .2rem; font-size: .84rem; }
.meta div { display: grid; grid-template-columns: 5.5rem minmax(0, 1fr); gap: .4rem; }
.meta dt { color: var(--muted); }
.meta dd { margin: 0; overflow-wrap: anywhere; }
.badge { display: inline-block; padding: .12rem .45rem; border-radius: .3rem; font-size: .82rem; }
.status-ok { background: #dcfce7; color: #14532d; }
.status-failed { background: #fee2e2; color: #7f1d1d; }
.status-missing { background: #fef3c7; color: #713f12; }
pre { margin: .3rem 0 .7rem; padding: .7rem; border: 1px solid #eceef1; border-radius: .4rem; background: #fafafa; white-space: pre-wrap; overflow-wrap: anywhere; }
pre.response { background: #fbfdff; }
.failure, .missing-state { color: #7f1d1d; }
.missing-state { color: #713f12; }
.synthetic { color: var(--muted); font-size: .82rem; }
footer { padding-bottom: 2rem; color: var(--muted); font-size: .85rem; }
@media (max-width: 900px) { .columns { grid-template-columns: minmax(0, 1fr); } }
</style>
</head>
<body>
<header>
<h1>Prompt 문체 비교</h1>
<p class="lede">로컬 정적 HTML입니다. 이 renderer는 모델을 호출하지 않으며, 페이지는 앱 로그가 아닙니다. 검토 입력은 합성 자료만 사용합니다.</p>
"""
    tail = f"""</header>
<main>
{chr(10).join(sections)}
</main>
<footer><p>합성 응답은 renderer 검증에만 쓰고 실제 문체 품질 증거로 쓰지 않습니다.</p></footer>
</body>
</html>
"""
    return (
        head
        + f'<p class="banner {banner_class}">{_escape(banner_text)}</p>\n'
        + f'<p class="summary">{_escape(summary)}</p>\n'
        + tail
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render local before/after prompt responses as one static HTML page. "
            "Reads local files only; never calls a model or the network."
        ),
        epilog=(
            "Input records are JSON objects in .json (one object or an array) or\n"
            ".jsonl (one object per line). Required fields: fixture_id, input,\n"
            "route, prompt_id, provider, model, output_limit, status; effort is\n"
            "a string or null. status is ok, failed or missing. ok requires\n"
            "non-empty text; failed requires error_code. Optional synthetic: true\n"
            "marks renderer proof data. Omit --before for first authoring. A\n"
            "fixture in only one input is shown with the other side missing.\n"
            "\n"
            'Example: {"fixture_id":"case-001","input":"synthetic input",\n'
            '"route":"script.default","prompt_id":"revision-or-digest",\n'
            '"provider":"anthropic_api","model":"actual-model-id",\n'
            '"effort":"medium","output_limit":1200,"status":"ok",\n'
            '"text":"response text","synthetic":true}'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--before",
        type=Path,
        help="read-only before responses (.json or .jsonl); omit for first authoring",
    )
    parser.add_argument(
        "--after",
        type=Path,
        required=True,
        help="read-only after responses (.json or .jsonl)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="local HTML file to write; it must differ from both inputs",
    )
    return parser


def _check_paths(before: Path | None, after: Path, output: Path) -> None:
    inputs = [path for path in (before, after) if path is not None]
    for path in inputs:
        if not path.is_file():
            raise InputError(f"input is not a local file: {path.name}")
    if output.resolve() in {path.resolve() for path in inputs}:
        raise InputError("--output must not overwrite an input file")


def _write_page(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        _check_paths(args.before, args.after, args.output)
        before = _load_side(args.before, "before")
        after = _load_side(args.after, "after")
        page = render_page(before, after, before_provided=args.before is not None)
        _write_page(args.output, page)
    except InputError as exc:
        print(f"compare_prompt_style: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"compare_prompt_style: cannot write output: {exc}", file=sys.stderr)
        return 1
    count = len(set(before) | set(after))
    print(f"compare_prompt_style: rendered {count} fixture(s) to a local HTML page")
    return 0


if __name__ == "__main__":
    sys.exit(main())
