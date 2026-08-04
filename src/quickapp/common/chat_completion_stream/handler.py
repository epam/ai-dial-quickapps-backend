import logging
from collections.abc import AsyncIterable

from aidial_sdk.chat_completion import Choice
from injector import inject
from openai import APIError, BadRequestError
from openai.types.chat import ChatCompletionChunk
from pydantic import BaseModel, ConfigDict, Field

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.chat_completion_stream.argument_stream_presentation import (
    ArgumentStreamPresentation,
)
from quickapp.common.chat_completion_stream.chat_stream_sink_factory import ChatStreamSinkFactory
from quickapp.common.chat_completion_stream.driver import iter_chat_completion_events
from quickapp.common.chat_completion_stream.exceptions import (
    ChatStreamHandlerError,
    ChatStreamParseError,
)
from quickapp.common.chat_completion_stream.models import (
    ChatStreamEvent,
    ChunkUsageFootprint,
    NormalizedChoiceDelta,
)
from quickapp.common.chat_completion_stream.parse import parse_chat_completion_chunk
from quickapp.common.chat_completion_stream.stream_result import ChatStreamAccumulator
from quickapp.common.chat_completion_stream.stream_sink import ChatStreamSink
from quickapp.common.payload_logging import log_payload

logger = logging.getLogger(__name__)


class ChatStreamConfig(BaseModel):
    """Orchestrator: set ``destination`` (+ ``propagate_stages``). Deployment: set ``stage_wrapper``."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    destination: Choice | None = None
    stage_wrapper: BaseStageWrapper | None = None
    stream_content: bool = True
    propagate_stages: bool = False
    argument_stream_presentations: dict[str, ArgumentStreamPresentation] = Field(
        default_factory=dict
    )


class ChatCompletionStreamHandler:
    @inject
    def __init__(self, sink_factory: ChatStreamSinkFactory) -> None:
        self._sink_factory = sink_factory

    @classmethod
    def with_default_sinks(cls) -> "ChatCompletionStreamHandler":
        """Construct with the standard sink factory (unit tests / non-DI callers)."""
        return cls(ChatStreamSinkFactory())

    async def process_stream(
        self,
        *,
        chunks: AsyncIterable[ChatCompletionChunk],
        config: ChatStreamConfig,
    ) -> ChatStreamAccumulator:
        pipeline = self._sink_factory.create(config)
        for sink in pipeline.sinks:
            sink.on_stream_start()
        await self._run(chat_completion=chunks, sinks=pipeline.sinks)
        self._log_stream_accumulator(pipeline.accumulator)
        return pipeline.accumulator

    async def _run(
        self,
        *,
        chat_completion: AsyncIterable[ChatCompletionChunk],
        sinks: list[ChatStreamSink],
    ) -> None:
        succeeded = False
        try:
            async for event in iter_chat_completion_events(
                chat_completion,
                parse_chat_completion_chunk,
            ):
                self._apply_stream_event(event, sinks)
            succeeded = True
            for sink in sinks:
                sink.on_stream_success()
        except (BadRequestError, APIError, ChatStreamHandlerError):
            raise
        except Exception as exc:
            raise ChatStreamParseError("Failed to consume/parse chat completion stream.") from exc
        finally:
            if not succeeded:
                for sink in sinks:
                    sink.on_stream_failure()

    def _apply_stream_event(self, event: ChatStreamEvent, sinks: list[ChatStreamSink]) -> None:
        if isinstance(event, ChunkUsageFootprint):
            for sink in sinks:
                sink.on_usage(event)
        elif isinstance(event, NormalizedChoiceDelta):
            for sink in sinks:
                sink.on_delta(event)
        else:
            logger.warning("Unexpected event of type %s", type(event))

    @staticmethod
    def _log_stream_accumulator(result: ChatStreamAccumulator) -> None:
        tool_calls = result.tool_calls  # property rebuilds a list on each access
        logger.debug(
            "LLM response accumulated: content_length=%d, tool_calls=%s, attachments=%d, "
            "stages=%d, state_keys=%s, usage=%s",
            len(result.content),
            [tool.name for tool in tool_calls] if tool_calls else [],
            len(result.attachments),
            len(result.stages),
            list(result.state) if result.state else [],
            (
                f"{result.usage.prompt_tokens}/{result.usage.completion_tokens}"
                if result.usage
                else None
            ),
        )
        if result.content:
            log_payload(logger, "LLM response content: %s", result.content)
        for tool in tool_calls or []:
            log_payload(logger, "LLM tool call args (%s): %s", tool.name, tool.arguments)
        if result.attachments:
            log_payload(logger, "LLM response attachments: %s", result.attachments)
        if result.stages:
            log_payload(logger, "LLM response stages: %s", result.stages)
        if result.state:
            log_payload(logger, "LLM response state: %s", result.state)
