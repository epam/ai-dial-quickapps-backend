from typing import Any

from aidial_sdk.chat_completion import Attachment
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall
from pydantic import BaseModel, ConfigDict, Field


class NormalizedCustomContent(BaseModel):
    """Per-delta custom payload. ``attachments``: ``Attachment``"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    attachments: list[Attachment]
    stage_entries: list[tuple[int, dict[str, Any]]]
    state: dict[str, Any] | None


class NormalizedChoiceDelta(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    content: str | None = None
    custom: NormalizedCustomContent | None = None
    tool_calls: tuple[ChoiceDeltaToolCall, ...] = Field(default_factory=tuple)


class ChunkUsageFootprint(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    prompt_tokens: int | None = None
    completion_tokens: int | None = None


ChatStreamEvent = ChunkUsageFootprint | NormalizedChoiceDelta
"""Emitted by ``consume_chat_completion_chunks``: usage footprint or one choice delta."""
