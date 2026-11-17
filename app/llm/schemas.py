"""Strict Pydantic v2 contract for LLM output."""

import json
import re

from pydantic import BaseModel, Field, ValidationError


class LlmParseError(ValueError):
    def __init__(self, content: str, reason: str):
        super().__init__(reason)
        self.content = content
        self.reason = reason


class LlmBoqItem(BaseModel):
    model_config = {"extra": "ignore"}

    line_id: int
    norm_description: str = Field(min_length=3, max_length=500)
    norm_category: str | None = None
    suggested_code: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class LlmNormalizationResult(BaseModel):
    model_config = {"extra": "ignore"}

    items: list[LlmBoqItem]


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.S)


def parse_llm_output(content: str) -> LlmNormalizationResult:
    """Tolerant of markdown fences and leading chatter; strict on schema."""
    match = _JSON_BLOCK_RE.search(content)
    if not match:
        raise LlmParseError(content, "no JSON object found in LLM output")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LlmParseError(content, f"invalid JSON: {exc}") from exc
    try:
        return LlmNormalizationResult.model_validate(data)
    except ValidationError as exc:
        raise LlmParseError(content, f"schema validation failed: {exc}") from exc
