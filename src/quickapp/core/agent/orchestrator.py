import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aidial_sdk.chat_completion import Choice
from aidial_sdk.chat_completion.request import CustomContent, Message, Role
from injector import ProviderOf, inject
from openai import APIError, AsyncStream
from openai.types.chat import ChatCompletionChunk

from quickapp.common import EXTERNAL_TOOL_NAMES, DeploymentUsage
from quickapp.common.abstract.tool_execution_history_policy import ToolExecutionHistoryPolicy
from quickapp.common.chat_completion_recovery import (
    STREAM_ACCUMULATION_RETRY_SCOPE,
    ChatCompletionRecoveryService,
)
from quickapp.common.chat_completion_stream.exceptions import ChatStreamHandlerError
from quickapp.common.chat_completion_stream.handler import (
    ChatCompletionStreamHandler,
    ChatStreamConfig,
)
from quickapp.common.chat_completion_stream.stream_result import ChatStreamAccumulator
from quickapp.common.chat_completion_stream.tool_call import AccumulatedToolCall
from quickapp.common.exceptions import OrchestratorExceedMaxIterationsException
from quickapp.common.lifecycle_logging import format_duration, format_event
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.payload_logging import log_payload, summarize_roles
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.presentation_settings import PresentationSettings
from quickapp.common.request_async_close_registry import RequestAsyncCloseRegistry
from quickapp.common.stage_close_registry import DeferredStageCloseRegistry
from quickapp.common.state_holder import StateHolder
from quickapp.common.url_sanitization import sanitize_url_for_log
from quickapp.config.application import ApplicationConfig
from quickapp.core.agent.assistant_invoker import AssistantInvoker
from quickapp.core.agent.models import STATE_KEY_ORCHESTRATOR, TOOL_EXECUTION_HISTORY
from quickapp.core.agent.tool_executor import ToolExecutor
from quickapp.usage_statistics.usage_statistics_service import UsageStatisticsService

logger = logging.getLogger(__name__)


def _log_messages(label: str, messages: list[Message]) -> None:
    """Log a message list as structure (count + role histogram) plus a gated payload."""
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("%s: count=%d, roles=%s", label, len(messages), summarize_roles(messages))
    log_payload(logger, f"{label}: %s", messages)


def _log_tool_calls(label: str, tool_calls: list[AccumulatedToolCall]) -> None:
    """Log tool calls as structure (names) plus a gated payload (arguments)."""
    logger.debug("%s: %s", label, [tc.name for tc in tool_calls])
    log_payload(logger, f"{label}: %s", tool_calls)


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
        deferred_stage_close_registry: DeferredStageCloseRegistry,
        chat_completion_recovery: ChatCompletionRecoveryService,
        tool_execution_history_policies: list[ToolExecutionHistoryPolicy],
        tool_names: EXTERNAL_TOOL_NAMES,
        request_async_close_registry: RequestAsyncCloseRegistry,
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
        self.__total_tool_calls = 0
        self.__completion_kind = "completed"
        self.__MAX_ITERATIONS_COUNT = app_config.orchestrator.max_iterations
        self.__orchestrator_deployment_name = app_config.orchestrator.deployment.deployment_id
        self.__propagate_orchestrator_stages: bool = app_config.orchestrator.propagate_stages
        self.__usage_statistics_list: list[DeploymentUsage] = []
        self.__perf_timer: PerformanceTimer = perf_timer
        self.__period_name = "orchestrator_invocation"
        self.__deferred_stage_close_registry: DeferredStageCloseRegistry = (
            deferred_stage_close_registry
        )
        self.__chat_completion_recovery = chat_completion_recovery
        self.__tool_execution_history_policies: list[ToolExecutionHistoryPolicy] = (
            tool_execution_history_policies
        )
        self.__tool_names: frozenset[str] = tool_names
        self.__request_async_close_registry: RequestAsyncCloseRegistry = (
            request_async_close_registry
        )
        self.__propagated_attachment_urls: set[str] = set()

    @property
    def iteration_count(self) -> int:
        return self.__iterations_counter

    @property
    def total_tool_calls(self) -> int:
        return self.__total_tool_calls

    @property
    def completion_kind(self) -> str:
        """``completed`` or ``external_tool_calls`` — how the loop terminated."""
        return self.__completion_kind

    @asynccontextmanager
    async def _persisting_state(self) -> AsyncIterator[None]:
        exc_to_reraise: BaseException | None = None
        try:
            yield
        except BaseException as exc:
            exc_to_reraise = exc
            logger.warning("Orchestrator interrupted by %s, saving state before re-raising", exc)
        finally:
            self.__deferred_stage_close_registry.flush(failed=exc_to_reraise is not None)
            # Close any per-request async resources (e.g. live MCP sessions) held open
            # for the duration of the request. Runs on both success and error paths.
            await self.__request_async_close_registry.aclose_all()
            # Store history in state.tool_execution_history for restoring on next request
            tool_execution_history = self._build_tool_execution_history()
            if tool_execution_history:
                if exc_to_reraise is None and self._is_terminal_completion():
                    for policy in self.__tool_execution_history_policies:
                        tool_execution_history = policy.apply(tool_execution_history)
                self.__state_holder.add_state(TOOL_EXECUTION_HISTORY, tool_execution_history)

            self.__choice.set_state(self.__state_holder.get_state())
            if self.__usage_statistics_list and self.__SHOW_USAGE_STATISTICS:
                await self.__usage_statistics_service.process_usage_statistics(
                    self.__usage_statistics_list
                )
            state = self.__state_holder.get_state()
            logger.debug("State holder keys: %s", list(state))
            log_payload(logger, "State holder: %s", state)

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

        model_call_start = time.perf_counter()
        stream_result = await self.__invoke_and_accumulate_stream_with_recovery()
        model_call_duration = time.perf_counter() - model_call_start

        tool_calls = stream_result.tool_calls

        usage = stream_result.usage
        logger.info(
            format_event(
                "Model call completed",
                iteration=self.__iterations_counter,
                deployment=self.__orchestrator_deployment_name,
                duration=format_duration(model_call_duration),
                finish="tool_calls" if tool_calls else "stop",
                tools=[tc.name for tc in tool_calls] if tool_calls else None,
                content_length=len(stream_result.content),
                tokens=(f"{usage.prompt_tokens}/{usage.completion_tokens}" if usage else None),
            )
        )

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
        _log_messages("Message from agent", self.__messages_context.messages)

        if not tool_calls:
            self.__perf_timer.stop_period(period)
            self.__deferred_stage_close_registry.flush()
            return False

        if self.__tool_names:
            external = [tc for tc in tool_calls if tc.name in self.__tool_names]
            internal = [tc for tc in tool_calls if tc.name not in self.__tool_names]
        else:
            external = []
            internal = tool_calls

        if internal:
            await self._execute_internal_tool_calls(internal)

        if external:
            self._surface_external_tool_calls(external, period)
            return False

        self.__perf_timer.stop_period(period)
        _log_messages("Message from context", self.__messages_context.messages)
        return True

    async def _execute_internal_tool_calls(self, tool_calls: list[AccumulatedToolCall]) -> None:
        self.__total_tool_calls += len(tool_calls)
        _log_tool_calls("Agent requests internal tool calls", tool_calls)
        tool_call_results = await self.__tool_executor.execute(tool_calls)
        if not tool_call_results:
            names = [tc.name for tc in tool_calls]
            raise RuntimeError(f"Tool call(s) {names} doesn't return any result.")

        logger.debug("Tool call results: count=%d", len(tool_call_results))
        log_payload(logger, "Tool call results: %s", tool_call_results)
        for tool_call_result in tool_call_results:
            tool_call_result_message = tool_call_result.to_tool_message()
            self.__messages_context.append_message(tool_call_result_message)
            for attachment in tool_call_result.propagate_to_choice:
                url = attachment.url
                if url is not None:
                    if url in self.__propagated_attachment_urls:
                        logger.debug(
                            "Skipping duplicate attachment URL %s", sanitize_url_for_log(url)
                        )
                        continue
                    self.__propagated_attachment_urls.add(url)
                self.__choice.add_attachment(**attachment.model_dump(exclude={"index"}))
            if tool_call_result.usage and self.__SHOW_USAGE_STATISTICS:
                self.__usage_statistics_list.extend(tool_call_result.usage)

    def _surface_external_tool_calls(
        self, tool_calls: list[AccumulatedToolCall], period: str
    ) -> None:
        self.__total_tool_calls += len(tool_calls)
        self.__completion_kind = "external_tool_calls"
        _log_tool_calls("Surfacing external tool calls to client", tool_calls)
        for tc in tool_calls:
            self.__choice.create_function_tool_call(tc.id, tc.name, tc.arguments)
        self.__perf_timer.stop_period(period)
        self.__deferred_stage_close_registry.flush()

    async def __invoke_and_accumulate_stream_with_recovery(self) -> ChatStreamAccumulator:
        """Invoke assistant and consume stream; on APIError during stream, run recovery once."""
        while True:
            assistant_invoker = self.__assistant_invoker_provider.get()
            chat_completion_stream = await assistant_invoker.invoke()
            try:
                return await self.accumulate_stream(chat_completion_stream)
            except APIError as e:
                self.__chat_completion_recovery.apply_message_recovery(
                    e, retry_scope=STREAM_ACCUMULATION_RETRY_SCOPE
                )

    async def accumulate_stream(
        self, chat_completion_stream: AsyncStream[ChatCompletionChunk]
    ) -> ChatStreamAccumulator:
        try:
            return await self.__stream_handler.process_stream(
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

    def _build_tool_execution_history(self) -> list[dict[str, object]]:
        """Build tool execution history by extracting ASSISTANT and TOOL messages.

        Stores messages directly to preserve parallel tool call grouping.
        Only includes ASSISTANT messages with tool_calls and TOOL messages.
        ASSISTANT messages whose tool calls are all external (client-side) are excluded
        because they are surfaced via create_function_tool_call, not executed server-side.
        For mixed ASSISTANT messages (both internal and external tool calls), external
        tool calls are stripped so that reconstruction produces valid LLM history.
        """
        history: list[dict[str, object]] = []

        for msg in reversed(self.__messages_context.messages):
            if msg.role == Role.USER:
                break
            if msg.role == Role.TOOL:
                history.append(msg.model_dump(mode="json", exclude_none=True))
            elif (
                msg.role == Role.ASSISTANT
                and msg.tool_calls
                and not self._is_all_external(msg.tool_calls)
            ):
                msg_dict = msg.model_dump(mode="json", exclude_none=True)
                if self.__tool_names and msg_dict.get("tool_calls"):
                    msg_dict["tool_calls"] = [
                        tc
                        for tc in msg_dict["tool_calls"]
                        if tc.get("function", {}).get("name") not in self.__tool_names
                    ]
                history.append(msg_dict)

        return history[::-1]

    def _is_all_external(self, tool_calls: list) -> bool:
        """True if every tool call in the list is an external (client-side) tool."""
        return bool(self.__tool_names) and all(
            tc.function.name in self.__tool_names for tc in tool_calls
        )

    def _is_terminal_completion(self) -> bool:
        """True when the latest message is a final assistant response (no tool calls)."""
        messages = self.__messages_context.messages
        if not messages:
            return False
        last = messages[-1]
        return bool(last.role == Role.ASSISTANT and not last.tool_calls)
