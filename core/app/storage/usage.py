"""Read side of the usage ledger and the versioned price table.

Cost is never stored on an event: this module sums token counts and applies the
price table when a total is requested. Each token-class line is rounded half up
to integer micro USD once, and an unknown price stays null instead of becoming
zero.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from app.schemas.usage import UsageEvent, UsagePage
from app.storage.sqlite import Database

MICRO_PER_UNIT = 1_000_000
"""Prices are integer micro USD per million tokens, so one product is micro USD."""

PRICE_KEYS = ("input", "output", "cache_read", "cache_write")


@dataclass(frozen=True)
class TokenPrice:
    """Integer micro USD per million tokens; None means the price is unknown."""

    input: int | None
    output: int | None
    cache_read: int | None
    cache_write: int | None


@dataclass(frozen=True)
class PriceTable:
    version: str
    llm: Mapping[tuple[str, str], TokenPrice]

    @classmethod
    def load(cls, path: Path) -> PriceTable:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{path} must contain a mapping")
        version = raw.get("version")
        if not isinstance(version, str) or not version:
            raise ValueError(f"{path} must have a version")
        llm = raw.get("llm") or {}
        if not isinstance(llm, dict):
            raise ValueError(f"{path}: llm must be a mapping")
        entries: dict[tuple[str, str], TokenPrice] = {}
        for provider, models in llm.items():
            if not isinstance(provider, str) or not isinstance(models, dict):
                raise ValueError(f"{path}: llm entries must be provider mappings")
            for model, values in models.items():
                if not isinstance(model, str) or not isinstance(values, dict):
                    raise ValueError(f"{path}: model entries must be mappings")
                entries[(provider, model)] = TokenPrice(
                    input=_price(values.get("input")),
                    output=_price(values.get("output")),
                    cache_read=_price(values.get("cache_read")),
                    cache_write=_price(values.get("cache_write")),
                )
        return cls(version=version, llm=entries)

    def line_cost(
        self,
        provider: str,
        model: str | None,
        *,
        input_tokens: int | None,
        output_tokens: int | None,
        cache_read_tokens: int | None,
        cache_write_tokens: int | None,
    ) -> int | None:
        """One model's token lines in integer micro USD, rounded once per line."""
        if model is None:
            return None
        price = self.llm.get((provider, model))
        if price is None:
            return None
        tokens = (
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_write_tokens,
        )
        rates = (price.input, price.output, price.cache_read, price.cache_write)
        total = 0
        for count, rate in zip(tokens, rates, strict=True):
            if count is None or count == 0:
                continue
            if rate is None:
                return None
            total += _round_half_up(count * rate)
        return total


class SqliteUsageReader:
    """UsageReader over the `usage_events` table and the current price table."""

    def __init__(self, db: Database, prices: PriceTable) -> None:
        self._db = db
        self._prices = prices

    def events(
        self,
        owner_id: str,
        start: datetime,
        end: datetime,
        cursor: str | None,
        limit: int,
    ) -> UsagePage:
        start_text = _utc_text(start)
        end_text = _utc_text(end)
        params: list[Any] = [owner_id, start_text, end_text]
        after = ""
        if cursor is not None:
            occurred_at, event_id = _decode_cursor(cursor)
            params.extend([occurred_at, occurred_at, event_id])
            after = (
                " AND (occurred_at > ? OR (occurred_at = ? AND id > ?))"
            )
        page_size = max(1, limit)
        params.append(page_size + 1)
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT id, owner_id, occurred_at, job_id, attempt, call_seq, try_index, "
                "stage, provider, model, credential_id, input_tokens, output_tokens, "
                "cache_read_tokens, cache_write_tokens, outcome, price_version "
                "FROM usage_events "
                "WHERE owner_id = ? AND occurred_at >= ? AND occurred_at < ?"
                + after
                + " ORDER BY occurred_at, id LIMIT ?",
                params,
            ).fetchall()
        items = [_event(row) for row in rows[:page_size]]
        next_cursor = None
        if len(rows) > page_size and items:
            last = items[-1]
            next_cursor = _encode_cursor(last.occurred_at, last.id)
        return UsagePage(items=items, next_cursor=next_cursor)

    def video_cost(self, owner_id: str, video_id: str) -> int | None:
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT e.provider, e.model, "
                "SUM(e.input_tokens), SUM(e.output_tokens), "
                "SUM(e.cache_read_tokens), SUM(e.cache_write_tokens) "
                "FROM usage_events e JOIN jobs j ON j.id = e.job_id "
                "WHERE e.owner_id = ? AND e.owner_id = j.owner_id AND j.video_id = ? "
                "GROUP BY e.provider, e.model "
                "ORDER BY e.provider, e.model",
                (owner_id, video_id),
            ).fetchall()
        if not rows:
            return None
        total = 0
        for provider, model, input_tokens, output_tokens, cache_read, cache_write in rows:
            cost = self._prices.line_cost(
                provider,
                model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
            )
            if cost is None:
                return None
            total += cost
        return total


def _price(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("price must be a non-negative integer or null")
    return value


def _round_half_up(numerator: int) -> int:
    return (numerator + MICRO_PER_UNIT // 2) // MICRO_PER_UNIT


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _event(row: tuple[Any, ...]) -> UsageEvent:
    return UsageEvent.model_validate(
        {
            "id": row[0],
            "owner_id": row[1],
            "occurred_at": row[2],
            "job_id": row[3],
            "attempt": row[4],
            "call_seq": row[5],
            "try_index": row[6],
            "stage": row[7],
            "provider": row[8],
            "model": row[9],
            "credential_id": row[10],
            "input_tokens": row[11],
            "output_tokens": row[12],
            "cache_read_tokens": row[13],
            "cache_write_tokens": row[14],
            "outcome": row[15],
            "price_version": row[16],
        }
    )


def _encode_cursor(occurred_at: datetime, event_id: str) -> str:
    raw = json.dumps([occurred_at.isoformat(), event_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        occurred_at, event_id = json.loads(raw)
    except (ValueError, TypeError, UnicodeError) as error:
        raise ValueError("invalid usage cursor") from error
    if not isinstance(occurred_at, str) or not isinstance(event_id, str):
        raise ValueError("invalid usage cursor")
    return occurred_at, event_id


__all__ = ["PriceTable", "SqliteUsageReader", "TokenPrice"]
