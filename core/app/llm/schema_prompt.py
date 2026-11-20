"""Prompt text for providers that cannot force a response schema."""

from __future__ import annotations

import json
from typing import Any


def schema_instruction(schema: dict[str, Any]) -> str:
    text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    return (
        "Return one JSON object that validates against this schema, "
        "with no Markdown code fence and no text outside the object:\n" + text
    )
