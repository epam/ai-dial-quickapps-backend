from typing import Any

from aidial_sdk.chat_completion import Attachment

from experiment.chat_stream_shared.models import (
    ChunkUsageFootprint,
    NormalizedChoiceDelta,
    NormalizedCustomContent,
)
from experiment.chat_stream_shared.openai_custom import attachment_kwargs, normalize_attachment


class NormalizedCustomContentBuilder:
    """Builder for NormalizedCustomContent that skips empty results."""

    def __init__(self) -> None:
        self._sdk_attachments: list[Attachment] = []
        self._stage_entries: list[tuple[int, dict[str, Any]]] = []
        self._state: dict[str, Any] | None = None

    def add_attachments(self, raw_attachments: Any) -> "NormalizedCustomContentBuilder":
        if not isinstance(raw_attachments, list):
            return self
        for attachment in raw_attachments:
            if isinstance(attachment, dict):
                normalize_attachment(attachment)
                kwargs = attachment_kwargs(attachment)
                self._sdk_attachments.append(Attachment(**kwargs))
        return self

    def add_stages(self, raw_stages: Any) -> "NormalizedCustomContentBuilder":
        if not isinstance(raw_stages, list):
            return self
        for position, item in enumerate(raw_stages):
            if isinstance(item, dict):
                self._stage_entries.append((position, item))
        return self

    def set_state(self, raw_state: Any) -> "NormalizedCustomContentBuilder":
        if isinstance(raw_state, dict):
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


def _openai_custom_dict_to_normalized(raw: dict[str, Any]) -> NormalizedCustomContent | None:
    if not raw:
        return None
    return (
        NormalizedCustomContentBuilder()
        .add_attachments(raw.get("attachments"))
        .add_stages(raw.get("stages"))
        .set_state(raw.get("state"))
        .build()
    )


def parse_openai_chat_completion_chunk(
        chunk: Any,
) -> tuple[ChunkUsageFootprint | None, list[NormalizedChoiceDelta]]:
    """Footprint is ``None`` when the chunk has no ``usage`` (typical mid-stream chunks)."""
    usage = _extract_usage_footprint(chunk)
    choices = getattr(chunk, "choices", None)
    if not choices:
        return usage, []

    out = [_build_normalized_delta(ch) for ch in choices if getattr(ch, "delta", None)]
    return usage, out


def _extract_usage_footprint(chunk: Any) -> ChunkUsageFootprint | None:
    u = getattr(chunk, "usage", None)
    if u is None:
        return None
    return ChunkUsageFootprint(
        prompt_tokens=getattr(u, "prompt_tokens", None),
        completion_tokens=getattr(u, "completion_tokens", None),
    )


def _build_normalized_delta(choice: Any) -> NormalizedChoiceDelta:
    delta = getattr(choice, "delta", None)
    content = getattr(delta, "content", None)
    custom_raw = getattr(delta, "custom_content", None)
    custom = (
        _openai_custom_dict_to_normalized(custom_raw)
        if isinstance(custom_raw, dict)
        else None
    )
    tool_raw = getattr(delta, "tool_calls", None)
    tool_calls: tuple[Any, ...] = (
        tuple(tool_raw) if tool_raw and not isinstance(tool_raw, tuple) else ()
    )
    return NormalizedChoiceDelta(content=content, custom=custom, tool_calls=tool_calls)
