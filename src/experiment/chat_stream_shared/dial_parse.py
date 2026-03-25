"""Map Dial client ChatCompletionChunk stream items to normalized stream events."""

from typing import Any

from chat_stream_shared.models import (
    ChunkUsageFootprint,
    NormalizedChoiceDelta,
    NormalizedCustomContent,
)


def parse_dial_chat_completion_chunk(
    chunk: Any,
) -> tuple[ChunkUsageFootprint | None, list[NormalizedChoiceDelta]]:
    statistics = (chunk.model_extra or {}).get("statistics", {}).get("usage_per_model", {})
    footprint = ChunkUsageFootprint(
        raw_usage=chunk.usage if chunk.usage else None,
        statistics=statistics,
    )
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return footprint, []
    out: list[NormalizedChoiceDelta] = []
    for ch in choices:
        delta = getattr(ch, "delta", None)
        if not delta:
            continue
        content = getattr(delta, "content", None)
        custom = _dial_custom_to_normalized(getattr(delta, "custom_content", None))
        out.append(NormalizedChoiceDelta(content=content, custom=custom, tool_calls=()))
    return footprint, out


def _dial_custom_to_normalized(custom_content: Any) -> NormalizedCustomContent | None:
    if not custom_content:
        return None
    attachments = getattr(custom_content, "attachments", None)
    if attachments:
        return NormalizedCustomContent(
            sdk_attachments=list(attachments),
            stage_entries=[],
            state=None,
        )
    state = getattr(custom_content, "state", None)
    if state:
        return NormalizedCustomContent(sdk_attachments=[], stage_entries=[], state=state)
    return None
