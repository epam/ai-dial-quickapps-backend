import logging
import sys
import time
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from aidial_sdk.chat_completion import Status
from injector import AssistedBuilder
from pydantic import BaseModel, Field

from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.chat_completion_stream.adopted_tool_stage import AdoptedToolStage
from quickapp.common.chat_completion_stream.argument_stream_presentation import (
    ArgumentStreamMode,
    ArgumentStreamPresentation,
)
from quickapp.common.lifecycle_logging import format_duration, format_event
from quickapp.common.parameter_stage_format import resolve_tool_stage_display_name
from quickapp.common.payload_logging import log_payload
from quickapp.common.stage_close_registry import (
    DeferredStageCloseRegistry,
    ImmediateStageCloseRegistry,
)
from quickapp.config.application import StageDisplayLevel
from quickapp.config.tools.base import BaseOpenAITool
from quickapp.config.tools.base import BaseTool as _BaseToolConfig
from quickapp.config.tools.base import OpenAiToolConfig
from quickapp.config.tools.tool_fallback import RetryStrategyModel

from .exceptions import InvalidToolCallParameterException, ToolTimeoutError
from .perf_timer.perf_timer import PerformanceTimer
from .tool_call_result import ToolCallResult
from .tool_fallback.processor import FallbackProcessor
from .utils import matches_type, substitute_media_type

logger = logging.getLogger(__name__)

# Upper bound on an error message echoed back to the model as a retry instruction.
_MAX_RETRY_MESSAGE_CHARS = 2000


def _cap_retry_message(message: str) -> str:
    """Bound an error message before it is fed back into the model's context.

    Any tool can author an ``InvalidToolCallParameterException`` message, and this is the
    line that puts it into the next LLM call. A message that accidentally embeds a payload
    (an inline ``data:`` URI, a response body) would otherwise be able to push the
    conversation past the context window. No legitimate error needs more than this.
    """
    if len(message) <= _MAX_RETRY_MESSAGE_CHARS:
        return message
    return f"{message[:_MAX_RETRY_MESSAGE_CHARS]}... (truncated)"


class StagedBaseTool(ABC, BaseModel, extra='allow'):
    stage_name_component: str | None = Field(None)
    # Opt-in: when set, orchestrator streams argument bodies into the tool stage.
    argument_stream_mode: ClassVar[ArgumentStreamMode | None] = None

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[BaseStageWrapper],
        perf_timer: PerformanceTimer,
        tool_config: _BaseToolConfig,
        stage_display_level: StageDisplayLevel,
        deferred_stage_close_registry: (
            DeferredStageCloseRegistry | ImmediateStageCloseRegistry | None
        ) = None,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.__stage_wrapper_builder: AssistedBuilder[BaseStageWrapper] = stage_wrapper_builder
        self._tool_config: _BaseToolConfig = tool_config
        self.__perf_timer: PerformanceTimer = perf_timer
        self.__deferred_stage_close_registry: (
            DeferredStageCloseRegistry | ImmediateStageCloseRegistry
        ) = (deferred_stage_close_registry or ImmediateStageCloseRegistry())
        self.__argument_transformers: list[ToolArgumentTransformer] = argument_transformers or []
        self.__stage_display_level: StageDisplayLevel = stage_display_level

    @property
    def tool_config(self):
        return self._tool_config

    def build_argument_stream_presentation(self) -> ArgumentStreamPresentation | None:
        mode = type(self).argument_stream_mode
        if mode is None:
            return None
        return ArgumentStreamPresentation.from_tool_config(self._tool_config, mode)

    def openai_function_name(self) -> str | None:
        if not isinstance(self._tool_config, BaseOpenAITool):
            return None
        return self._tool_config.open_ai_tool.function.name

    def should_suppress_info_stage(self) -> bool:
        """Whether INFO-level tool stages (incl. early stream stages) must be hidden."""
        return self.__should_suppress(StageDisplayLevel.INFO)

    def stage_display_name(self) -> str | None:
        return resolve_tool_stage_display_name(self._tool_config, self.stage_name_component)

    @abstractmethod  # pragma: no cover
    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None,
        tool_call_id: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult: ...

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Use only async version")

    def __should_suppress(self, stage_level: StageDisplayLevel) -> bool:
        level = self.__stage_display_level

        if level == StageDisplayLevel.NONE:
            return True

        if level == StageDisplayLevel.DEBUG:
            return False

        if stage_level == StageDisplayLevel.ERROR:
            return False

        if stage_level == StageDisplayLevel.DEBUG:
            return True

        # INFO stage_level from here
        if level == StageDisplayLevel.ERROR:
            return True

        # INFO level: also honour deprecated display.stage.show=false
        display = self._tool_config.display
        if display and display.stage and not display.stage.show:
            return True

        return False

    async def arun(
        self,
        tool_call_id: str,
        *args: Any,
        stage_level: StageDisplayLevel = StageDisplayLevel.INFO,
        adopted_stage: AdoptedToolStage | None = None,
        **kwargs: Any,
    ) -> ToolCallResult:
        if self.__should_suppress(stage_level):
            self._discard_adopted_stage(adopted_stage)
            # Stage is suppressed, but we still route through __run_tool_body so that
            # tool exceptions are caught and converted to fallback results instead of
            # propagating unhandled and crashing the chat.
            return await self.__run_tool_body(tool_call_id, None, *args, **kwargs)

        if adopted_stage is not None:
            stage_wrapper = self.__stage_wrapper_builder.build(
                tool_config=self._tool_config,
                stage_name=self.stage_name_component,
                stage=adopted_stage.stage,
                already_open=True,
                start_time=adopted_stage.start_time,
            )
        else:
            stage_wrapper = self.__stage_wrapper_builder.build(
                tool_config=self._tool_config,
                stage_name=self.stage_name_component,
            )
        display = self._tool_config.display
        defer_close = bool(display and display.stage and display.stage.defer_close)
        # If the stream already rendered the Request body, skip the full
        # add_parameters dump to avoid duplicating formatted content.
        skip_parameters = bool(adopted_stage is not None and adopted_stage.request_body_streamed)

        if defer_close:
            stage_wrapper.__enter__()
            try:
                result = await self.__run_tool_body(
                    tool_call_id,
                    stage_wrapper,
                    *args,
                    skip_parameters=skip_parameters,
                    **kwargs,
                )
                self.__deferred_stage_close_registry.defer_close(stage_wrapper)
                return result
            except BaseException:
                stage_wrapper.__exit__(*sys.exc_info())
                raise
        else:
            with stage_wrapper:
                return await self.__run_tool_body(
                    tool_call_id,
                    stage_wrapper,
                    *args,
                    skip_parameters=skip_parameters,
                    **kwargs,
                )

    @staticmethod
    def _discard_adopted_stage(adopted_stage: AdoptedToolStage | None) -> None:
        if adopted_stage is None:
            return
        try:
            adopted_stage.stage.close(status=Status.COMPLETED)
        except Exception as exc:
            logger.warning("Failed to close discarded adopted tool stage: %s", exc, exc_info=True)

    async def __run_tool_body(
        self,
        tool_call_id: str,
        stage_wrapper: BaseStageWrapper | None,
        *args: Any,
        skip_parameters: bool = False,
        **kwargs: Any,
    ) -> ToolCallResult:
        # The failure WARNING is written by _run_in_stage_report_success; here we only
        # translate it into stage UI and a fallback result (hands-onward layer).
        try:
            return await self._run_in_stage_report_success(
                tool_call_id,
                stage_wrapper,
                *args,
                skip_parameters=skip_parameters,
                **kwargs,
            )
        except InvalidToolCallParameterException as e:
            self._report_error_to_stage(stage_wrapper, e)
            return FallbackProcessor.process_fallback(
                [
                    RetryStrategyModel(
                        instructions=f"Parameter {e.parameter_name} is invalid, try to call the tool again with fixed exception: {_cap_retry_message(e.message)}"
                    )
                ],
                tool_call_id,
                e,
            )
        except Exception as e:
            fallback = self._tool_config.fallback_configuration
            if fallback.display_error_in_stage or isinstance(e, ToolTimeoutError):
                error_to_show = e
            else:
                error_to_show = Exception("An error occurred while executing the tool.")
            self._report_error_to_stage(stage_wrapper, error_to_show)
            return FallbackProcessor.process_fallback(fallback.strategies, tool_call_id, e)

    def _report_error_to_stage(
        self,
        stage_wrapper: BaseStageWrapper | None,
        error: Exception,
    ) -> None:
        """Write an error into the stage.

        If ``stage_wrapper`` is not None (stage was already opened), the error is
        appended to it. If ``stage_wrapper`` is None (stage was suppressed because
        ``stage_display_level=error`` hid the INFO-level call), a stage is created
        on-the-fly so the failure is still visible to the user.

        When ``stage_display_level=none``, stages are never created — not even for
        errors — so this method is a no-op.
        """
        if self.__stage_display_level == StageDisplayLevel.NONE:
            return

        if stage_wrapper is not None:
            stage_wrapper.add_exception(error)
            return

        # Stage was suppressed, but an error occurred — open a stage on-the-fly,
        # write the error, and close it.
        on_the_fly_stage = self.__stage_wrapper_builder.build(
            tool_config=self._tool_config,
            stage_name=self.stage_name_component,
        )
        with on_the_fly_stage:
            on_the_fly_stage.add_exception(error)

    def enrich_openai_tool_schema(self, open_ai_tool: OpenAiToolConfig) -> OpenAiToolConfig:
        return open_ai_tool

    async def _pre_process_params(self, **kwargs: Any) -> dict[str, Any]:
        for transformer in self.__argument_transformers:
            kwargs = await transformer.transform(kwargs)
        return kwargs

    def _resolve_tool_name(self) -> str:
        """Best-effort tool name for lifecycle logging (the OpenAI function name,
        falling back to a set ``name`` attribute or the class name)."""
        if isinstance(self._tool_config, BaseOpenAITool):
            return self._tool_config.open_ai_tool.function.name
        return getattr(self, "name", None) or type(self).__name__

    async def _run_in_stage_report_success(
        self,
        tool_call_id: str,
        stage_wrapper: BaseStageWrapper | None,
        *args: Any,
        skip_parameters: bool = False,
        **kwargs: Any,
    ) -> ToolCallResult:
        tool_name = self._resolve_tool_name()
        timer_name = f"tool_{tool_call_id}"
        if stage_wrapper:
            timer_name = f"tool_{stage_wrapper.name}_{tool_call_id}"
        start = time.perf_counter()
        self.__perf_timer.start_period(timer_name, 3)
        try:
            params = await self._pre_process_params(**kwargs)
            if stage_wrapper:
                if skip_parameters:
                    # Arguments were already streamed into the adopted stage; only
                    # refine the title (e.g. py-interpreter ``title`` param).
                    stage_wrapper.append_title_from_params(params)
                else:
                    # TODO: filter params ro remove attachment_urls if it's empty
                    stage_wrapper.add_parameters(params)
            result: ToolCallResult = await self._run_in_stage_async(
                stage_wrapper, tool_call_id, *args, **params
            )
            result.tool_call_id = tool_call_id
            if result.attachments:
                attachment_cfg = self._tool_config.attachment
                filtered: list = []
                for a in result.attachments:
                    if matches_type(a.type, attachment_cfg.supported_types):
                        a.type = substitute_media_type(
                            a.type, attachment_cfg.media_type_substitution
                        )
                        filtered.append(a)
                        if matches_type(a.type, attachment_cfg.propagate_types_to_choice):
                            result.propagate_to_choice.append(a)
                result.attachments = filtered
            logger.debug(
                "Tool call %s finished: content_length=%d, attachments=%d",
                tool_call_id,
                len(result.content) if result.content else 0,
                len(result.attachments) if result.attachments else 0,
            )
            log_payload(logger, "Tool call %s result: %s", tool_call_id, result)
            logger.info(
                format_event(
                    "Tool call completed",
                    tool=tool_name,
                    tool_call_id=tool_call_id,
                    duration=format_duration(time.perf_counter() - start),
                    outcome="success",
                )
            )
            return result
        except Exception as e:
            # The single failure log for every tool type (ownership rule): exception type
            # and duration only, no response body or arguments. This replaces the
            # success-path completion event, so a failed call still yields exactly one line.
            logger.warning(
                format_event(
                    "Tool call failed",
                    tool=tool_name,
                    tool_call_id=tool_call_id,
                    duration=format_duration(time.perf_counter() - start),
                    error=type(e).__name__,
                ),
                exc_info=True,
            )
            raise
        finally:
            self.__perf_timer.stop_period(timer_name)
