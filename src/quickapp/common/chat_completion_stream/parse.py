"""Parse OpenAI-compatible streaming ``ChatCompletionChunk`` (orchestrator + deployment)."""

from __future__ import annotations

from typing import Any

from aidial_sdk.chat_completion import Attachment

from quickapp.agent._stage_delta_types import attachment_kwargs, normalize_attachment
from quickapp.common.chat_completion_stream.models import (
    ChunkUsageFootprint,
    NormalizedChoiceDelta,
    NormalizedCustomContent,
)


class NormalizedCustomContentBuilder:
    """Build ``NormalizedCustomContent`` from OpenAI ``custom_content`` dict fields."""

    def __init__(self) -> None:
        self._sdk_attachments: list[Attachment] = []
        self._stage_entries: list[tuple[int, dict[str, Any]]] = []
        self._state: dict[str, Any] | None = None

    def add_attachments(self, raw_attachments: Any) -> NormalizedCustomContentBuilder:
        if not isinstance(raw_attachments, list):
            return self
        for attachment in raw_attachments:
            if isinstance(attachment, dict):
                normalize_attachment(attachment)
                kwargs = attachment_kwargs(attachment)
                self._sdk_attachments.append(Attachment(**kwargs))
        return self

    def add_stages(self, raw_stages: Any) -> NormalizedCustomContentBuilder:
        if not isinstance(raw_stages, list):
            return self
        for position, item in enumerate(raw_stages):
            if isinstance(item, dict):
                self._stage_entries.append((position, item))
        return self

    def set_state(self, raw_state: Any) -> NormalizedCustomContentBuilder:
        # Match orchestrator: empty dict is absent (falsy), same as ``if state := custom_content.get("state")``.
        if raw_state and isinstance(raw_state, dict):
            self._state = raw_state
        return self

    def build(self) -> NormalizedCustomContent | None:
        if not self._sdk_attachments and not self._stage_entries and self._state is None:
            return None
        return NormalizedCustomContent(
            sdk_attachments=self._sdk_attachments,
            stage_entries=self._stage_entries,
            state=self._state,
        )


def _custom_content_from_dict(raw: dict[str, Any]) -> NormalizedCustomContent | None:
    if not raw:
        return None
    return (
        NormalizedCustomContentBuilder()
        .add_attachments(raw.get("attachments"))
        .add_stages(raw.get("stages"))
        .set_state(raw.get("state"))
        .build()
    )


def _custom_content_from_delta(custom_raw: Any) -> NormalizedCustomContent | None:
    """Normalize ``delta.custom_content`` (dict shape used by current stream providers)."""
    if custom_raw is None:
        return None
    if isinstance(custom_raw, dict):
        return _custom_content_from_dict(custom_raw)
    return None


def _usage_footprint(chunk: Any) -> ChunkUsageFootprint | None:
    u = getattr(chunk, "usage", None)
    if u is not None:
        return ChunkUsageFootprint(
            prompt_tokens=getattr(u, "prompt_tokens", None),
            completion_tokens=getattr(u, "completion_tokens", None),
            raw_usage=u,
        )
    return None


def _delta_tool_calls_tuple(delta: Any) -> tuple[Any, ...]:
    raw = getattr(delta, "tool_calls", None)
    if not raw:
        return ()
    if isinstance(raw, tuple):
        return raw
    return tuple(raw)


def _normalized_choice_delta(choice: Any) -> NormalizedChoiceDelta | None:
    delta = getattr(choice, "delta", None)
    if not delta:
        return None
    content = getattr(delta, "content", None)
    custom_raw = getattr(delta, "custom_content", None)
    return NormalizedChoiceDelta(
        content=content,
        custom=_custom_content_from_delta(custom_raw),
        tool_calls=_delta_tool_calls_tuple(delta),
    )


def parse_chat_completion_chunk(
    chunk: Any,
) -> tuple[ChunkUsageFootprint | None, list[NormalizedChoiceDelta]]:
    usage_footprint = _usage_footprint(chunk)

    choices = getattr(chunk, "choices", None)
    if not choices:
        return usage_footprint, []

    deltas: list[NormalizedChoiceDelta] = []
    for ch in choices:
        d = _normalized_choice_delta(ch)
        if d is not None:
            deltas.append(d)
    return usage_footprint, deltas
