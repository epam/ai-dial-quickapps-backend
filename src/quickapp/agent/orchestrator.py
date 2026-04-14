import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aidial_sdk.chat_completion import Choice
from aidial_sdk.chat_completion.request import CustomContent, Message, Role
from injector import ProviderOf, inject
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk

from quickapp.agent.assistant_invoker import AssistantInvoker
from quickapp.agent.models import STATE_KEY_ORCHESTRATOR, TOOL_EXECUTION_HISTORY
from quickapp.agent.tool_executor import ToolExecutor
from quickapp.common import DeploymentUsage
from quickapp.common.chat_completion_stream.exceptions import ChatStreamHandlerError
from quickapp.common.chat_completion_stream.handler import (
    ChatCompletionStreamHandler,
    ChatStreamConfig,
)
from quickapp.common.chat_completion_stream.stream_result import ChatStreamAccumulator
from quickapp.common.chat_completion_stream.tool_call import AccumulatedToolCall
from quickapp.common.exceptions import OrchestratorExceedMaxIterationsException
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.presentation_settings import PresentationSettings
from quickapp.common.state_holder import StateHolder
from quickapp.config.application import ApplicationConfig
from quickapp.usage_statistics.usage_statistics_service import UsageStatisticsService

logger = logging.getLogger(__name__)


@inject
class Orchestrator:

    def __init__(
        self,
        presentation_settings: PresentationSettings,
        messages_context: MessagesMixin,
        choice: Choice,
        state_holder: StateHolder,
        usage_statistics_service: UsageStatisticsService,
        tool_executor: ToolExecutor,
        assistant_invoker_provider: ProviderOf[AssistantInvoker],
        stream_handler: ChatCompletionStreamHandler,
        app_config: ApplicationConfig,
        perf_timer: PerformanceTimer,
    ) -> None:
        self.__messages_context: MessagesMixin = messages_context
        self.__choice: Choice = choice
        self.__state_holder: StateHolder = state_holder
        self.__usage_statistics_service: UsageStatisticsService = usage_statistics_service
        self.__SHOW_USAGE_STATISTICS = presentation_settings.show_usage_statistics
        self.__tool_executor = tool_executor
        self.__assistant_invoker_provider = assistant_invoker_provider
        self.__stream_handler = stream_handler
        self.__iterations_counter = 0
        self.__MAX_ITERATIONS_COUNT = app_config.orchestrator.max_iterations
        self.__orchestrator_deployment_name = app_config.orchestrator.deployment.name
        self.__propagate_orchestrator_stages: bool = app_config.orchestrator.propagate_stages
        self.__usage_statistics_list: list[DeploymentUsage] = []
        self.__perf_timer: PerformanceTimer = perf_timer
        self.__period_name = "orchestrator_invocation"

    @asynccontextmanager
    async def _persisting_state(self) -> AsyncIterator[None]:
        exc_to_reraise: BaseException | None = None
        try:
            yield
        except BaseException as exc:
            exc_to_reraise = exc
            logger.warning("Orchestrator interrupted by %s, saving state before re-raising", exc)
        finally:
            # Store history in state.tool_execution_history for restoring on next request
            tool_execution_history = self._build_tool_execution_history()
            if tool_execution_history:
                self.__state_holder.add_state(TOOL_EXECUTION_HISTORY, tool_execution_history)

            self.__choice.set_state(self.__state_holder.get_state())
            if self.__usage_statistics_list and self.__SHOW_USAGE_STATISTICS:
                await self.__usage_statistics_service.process_usage_statistics(
                    self.__usage_statistics_list
                )
            logger.debug(f"State holder: {self.__state_holder.get_state()}")

        if exc_to_reraise is not None:
            raise exc_to_reraise

    async def invoke(self):
        async with self._persisting_state():
            while await self._run_iteration():
                pass

    async def _run_iteration(self) -> bool:
        """Run a single orchestrator iteration. Returns True if the loop should continue."""
        self.__iterations_counter += 1
        if self.__iterations_counter > self.__MAX_ITERATIONS_COUNT:
            raise OrchestratorExceedMaxIterationsException()

        period = f"{self.__period_name}_{self.__iterations_counter}"
        self.__perf_timer.start_period(period, level=2)

        assistant_invoker = self.__assistant_invoker_provider.get()
        chat_completion_stream = await assistant_invoker.invoke()
        stream_result = await self.accumulate_stream(chat_completion_stream)

        tool_calls = stream_result.tool_calls

        # Thinking stages stay in custom_content (streamed to choice), not in state.
        response_state = dict(stream_result.state or {})
        state: dict[str, object] | None = (
            {STATE_KEY_ORCHESTRATOR: response_state} if response_state else None
        )

        custom_content_kwargs: dict[str, object] = {
            "attachments": stream_result.attachments,
        }
        if state:
            custom_content_kwargs["state"] = state
            # Persist orchestrator response state so it's available for the next request.
            for key, value in state.items():
                self.__state_holder.add_state(key, value)

        self.__messages_context.append_message(
            Message(
                role=Role.ASSISTANT,
                content=stream_result.content or " ",
                custom_content=CustomContent(**custom_content_kwargs),
                tool_calls=AccumulatedToolCall.to_sdk_tool_calls(tool_calls),
            )
        )

        if stream_result.usage and self.__SHOW_USAGE_STATISTICS:
            self.__usage_statistics_list.append(
                DeploymentUsage(
                    model_name=self.__orchestrator_deployment_name,
                    prompt_tokens=stream_result.usage.prompt_tokens,
                    completion_tokens=stream_result.usage.completion_tokens,
                )
            )
        self.__perf_timer.add_milestone(period, "assistant_response_received")
        logger.debug(f"Message from agent: {self.__messages_context.messages}")

        if not tool_calls:
            return False

        logger.debug(f"Agent requests tool calls: {tool_calls}")
        tool_call_results = await self.__tool_executor.execute(tool_calls)
        if not tool_call_results:
            raise RuntimeError(f"Tool call(s) {tool_calls} doesn't return any result.")

        logger.debug(f"Tool call results: {tool_call_results}")
        for tool_call_result in tool_call_results:
            tool_call_result_message = tool_call_result.to_tool_message()
            self.__messages_context.append_message(tool_call_result_message)
            for attachment in tool_call_result.propagate_to_choice:
                self.__choice.add_attachment(**attachment.model_dump(exclude={"index"}))
            if tool_call_result.usage and self.__SHOW_USAGE_STATISTICS:
                self.__usage_statistics_list.extend(tool_call_result.usage)

        self.__perf_timer.stop_period(period)
        logger.debug(f"Message from context: {self.__messages_context.messages}")
        return True

    async def accumulate_stream(
        self, chat_completion_stream: AsyncStream[ChatCompletionChunk]
    ) -> ChatStreamAccumulator:
        try:
            stream_accumulator = await self.__stream_handler.process_stream(
                chunks=chat_completion_stream,
                config=ChatStreamConfig(
                    destination=self.__choice,
                    stream_content=True,
                    propagate_stages=self.__propagate_orchestrator_stages,
                ),
            )
        except ChatStreamHandlerError:
            logger.exception("Orchestrator stream handling failed.")
            raise
        if stream_accumulator is None:
            raise RuntimeError("Assistant invocation returned no result.")
        return stream_accumulator

    def _build_tool_execution_history(self) -> list[dict[str, object]]:
        """Build tool execution history by extracting ASSISTANT and TOOL messages.

        Stores messages directly to preserve parallel tool call grouping.
        Only includes ASSISTANT messages with tool_calls and TOOL messages.
        """
        history: list[dict[str, object]] = []

        for msg in reversed(self.__messages_context.messages):
            if msg.role == Role.USER:
                break
            if msg.role == Role.TOOL or (msg.role == Role.ASSISTANT and msg.tool_calls):
                history.append(msg.model_dump(mode="json", exclude_none=True))

        return history[::-1]
