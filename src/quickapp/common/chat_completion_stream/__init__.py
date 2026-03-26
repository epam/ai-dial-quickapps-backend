"""Shared OpenAI-compatible chat completion stream parsing (orchestrator + deployment)."""

from quickapp.common.chat_completion_stream.driver import (
    ChatStreamEventHandler,
    consume_chat_completion_chunks,
)
from quickapp.common.chat_completion_stream.exceptions import (
    ChatStreamHandlerError,
    ChatStreamInvariantError,
    ChatStreamParseError,
    ChatStreamSinkWriteError,
)
from quickapp.common.chat_completion_stream.handler import (
    ChatCompletionStreamHandler,
    DeploymentStreamStrategyConfig,
    OrchestratorStreamStrategyConfig,
)
from quickapp.common.chat_completion_stream.models import (
    ChatStreamEvent,
    ChatStreamFootprintMode,
    ChunkUsageFootprint,
    NormalizedChoiceDelta,
    NormalizedCustomContent,
)
from quickapp.common.chat_completion_stream.parse import parse_chat_completion_chunk
from quickapp.common.chat_completion_stream.stream_result import (
    ChatStreamAccumulator,
    Usage,
    attachment_to_sdk,
)

__all__ = [
    "ChatStreamAccumulator",
    "ChatStreamEvent",
    "ChatStreamEventHandler",
    "ChatStreamFootprintMode",
    "ChatStreamHandlerError",
    "ChatStreamInvariantError",
    "ChatStreamParseError",
    "ChatStreamSinkWriteError",
    "ChatCompletionStreamHandler",
    "ChunkUsageFootprint",
    "DeploymentStreamStrategyConfig",
    "NormalizedChoiceDelta",
    "NormalizedCustomContent",
    "OrchestratorStreamStrategyConfig",
    "Usage",
    "attachment_to_sdk",
    "consume_chat_completion_chunks",
    "parse_chat_completion_chunk",
]
