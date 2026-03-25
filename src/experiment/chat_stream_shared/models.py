from __future__ import annotations

from typing import Any, Protocol

from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall
from pydantic import BaseModel, ConfigDict, Field


class NormalizedCustomContent(BaseModel):
    """Per-delta custom payload. `sdk_attachments`: SDK Attachment (orchestrator) or dial-client models (deployment)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    sdk_attachments: list[Any]
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
    raw_usage: Any = None
    statistics: Any = None


class StreamChunkVisitor(Protocol):
    def on_chunk_usage(self, fp: ChunkUsageFootprint) -> None: ...

    def on_choice_delta(self, delta: NormalizedChoiceDelta) -> None: ...
