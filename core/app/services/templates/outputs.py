"""Structured answers of the style_code, template_code and bgm_code routes.

The model returns code as a string plus the few manifest values it decides. The
geometry and length rules live in the validators, so a broken answer takes the
one invalid-output repair before any sandbox run.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.caption_layout import inside, intersects, safe_area
from app.schemas.common import Box, CaptionMode
from app.schemas.template_manifest import CharacterAnchors, Regions

FRAME = (1080, 1920)
MAX_LOOP_MS = 16000
MIN_LOOP_MS = 500
BEATS_PER_BAR = 4
CODE_LIMIT = 65536

Code = Annotated[str, Field(min_length=1, max_length=CODE_LIMIT)]
ShortText = Annotated[str, Field(min_length=1, max_length=40)]


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShortLabel(Answer):
    ko: ShortText
    en: ShortText


class StyleCodeAnswer(Answer):
    label: ShortLabel
    code: Code


def _inside_frame(box: Box) -> bool:
    return box.x + box.w <= FRAME[0] and box.y + box.h <= FRAME[1]


class TemplateCodeAnswer(Answer):
    label: ShortLabel
    code: Code
    regions: Regions
    character_anchors: CharacterAnchors
    caption_modes: Annotated[list[CaptionMode], Field(min_length=1, max_length=3)]
    dialog_box: bool

    @model_validator(mode="after")
    def _check_regions(self) -> TemplateCodeAnswer:
        regions = self.regions
        named = {
            name: box
            for name in ("title", "progress", "visual", "caption")
            if (box := getattr(regions, name)) is not None
        }
        for name, box in named.items():
            if not _inside_frame(box):
                raise ValueError(f"region {name} leaves the 1080x1920 frame")
        caption = regions.caption
        if not inside(caption, safe_area()):
            raise ValueError("caption must stay inside the safe band")
        for name, box in named.items():
            if name != "caption" and intersects(box, caption):
                raise ValueError(f"region {name} overlaps the caption")
        visual = regions.visual
        for side in ("left", "center", "right"):
            point = getattr(self.character_anchors, side)
            if not (
                visual.x <= point.x <= visual.x + visual.w
                and visual.y <= point.y <= visual.y + visual.h
            ):
                raise ValueError(f"anchor {side} is outside the visual region")
        if len(set(self.caption_modes)) != len(self.caption_modes):
            raise ValueError("caption_modes repeat")
        if CaptionMode.typewriter in self.caption_modes and not self.dialog_box:
            raise ValueError("typewriter captions need dialog_box")
        return self


class BgmCodeAnswer(Answer):
    label: ShortLabel
    code: Code
    bpm: Annotated[int, Field(ge=60, le=180)]
    bars: Annotated[int, Field(ge=1, le=16)]

    @property
    def loop_ms(self) -> int:
        return self.bars * BEATS_PER_BAR * 60000 // self.bpm

    @model_validator(mode="after")
    def _check_length(self) -> BgmCodeAnswer:
        if self.loop_ms > MAX_LOOP_MS:
            raise ValueError(f"loop is {self.loop_ms} ms; code BGM loops end at 16000 ms")
        if self.loop_ms < MIN_LOOP_MS:
            raise ValueError(f"loop is {self.loop_ms} ms; code BGM loops last at least 500 ms")
        return self


__all__ = [
    "FRAME",
    "MAX_LOOP_MS",
    "BgmCodeAnswer",
    "ShortLabel",
    "StyleCodeAnswer",
    "TemplateCodeAnswer",
]
