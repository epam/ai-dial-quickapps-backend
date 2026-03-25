"""Sandbox package: normalized chat completion stream chunks (orchestrator + deployment)."""

from chat_stream_shared.dial_parse import parse_dial_chat_completion_chunk
from chat_stream_shared.driver import consume_chat_completion_chunks
from chat_stream_shared.models import (
    ChunkUsageFootprint,
    NormalizedChoiceDelta,
    NormalizedCustomContent,
    StreamChunkVisitor,
)
from chat_stream_shared.openai_parse import parse_openai_chat_completion_chunk

__all__ = [
    "ChunkUsageFootprint",
    "NormalizedChoiceDelta",
    "NormalizedCustomContent",
    "StreamChunkVisitor",
    "consume_chat_completion_chunks",
    "parse_dial_chat_completion_chunk",
    "parse_openai_chat_completion_chunk",
]
