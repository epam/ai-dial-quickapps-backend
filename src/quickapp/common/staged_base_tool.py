import logging
import sys
from abc import ABC, abstractmethod
from typing import Any

from injector import AssistedBuilder
from pydantic import BaseModel, Field

from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.stage_close_registry import (
    DeferredStageCloseRegistry,
    ImmediateStageCloseRegistry,
)
from quickapp.config.tools.base import BaseTool as _BaseToolConfig
from quickapp.config.tools.tool_fallback import RetryStrategyModel

from .exceptions import InvalidToolCallParameterException, ToolTimeoutError
from .perf_timer.perf_timer import PerformanceTimer
from .tool_call_result import ToolCallResult
from .tool_fallback.processor import FallbackProcessor
from .utils import matches_type, substitute_media_type

logger = logging.getLogger(__name__)


class StagedBaseTool(ABC, BaseModel, extra='allow'):
    stage_name_component: str | None = Field(None)

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[BaseStageWrapper],
        perf_timer: PerformanceTimer,
        tool_config: _BaseToolConfig,
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

    @property
    def tool_config(self):
        return self._tool_config

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

    async def arun(
        self,
        tool_call_id: str,
        *args: Any,
        suppress_stage: bool = False,
        **kwargs: Any,
    ) -> ToolCallResult:
        display = self._tool_config.display
        if suppress_stage or (display and display.stage and not display.stage.show):
            return await self._run_in_stage_report_success(tool_call_id, None, *args, **kwargs)

        stage_wrapper = self.__stage_wrapper_builder.build(
            tool_config=self._tool_config,
            stage_name=self.stage_name_component,
        )
        defer_close = bool(display and display.stage and display.stage.defer_close)

        if defer_close:
            stage_wrapper.__enter__()
            try:
                result = await self.__run_tool_body(tool_call_id, stage_wrapper, *args, **kwargs)
                self.__deferred_stage_close_registry.defer_close(stage_wrapper)
                return result
            except BaseException:
                stage_wrapper.__exit__(*sys.exc_info())
                raise
        else:
            with stage_wrapper:
                return await self.__run_tool_body(tool_call_id, stage_wrapper, *args, **kwargs)

    async def __run_tool_body(
        self, tool_call_id: str, stage_wrapper: BaseStageWrapper, *args: Any, **kwargs: Any
    ) -> ToolCallResult:
        try:
            return await self._run_in_stage_report_success(
                tool_call_id, stage_wrapper, *args, **kwargs
            )
        except InvalidToolCallParameterException as e:
            logger.exception("Invalid parameter detected while running tool")
            stage_wrapper.add_exception(e)
            return FallbackProcessor.process_fallback(
                [
                    RetryStrategyModel(
                        instructions=f"Parameter {e.parameter_name} is invalid, try to call the tool again with fixed exception: {e.message}"
                    )
                ],
                tool_call_id,
                e,
            )
        except Exception as e:
            logger.exception("Error occurred while running tool")
            fallback = self._tool_config.fallback_configuration
            if fallback.display_error_in_stage or isinstance(e, ToolTimeoutError):
                stage_wrapper.add_exception(e)
            else:
                stage_wrapper.add_exception(
                    Exception("An error occurred while executing the tool.")
                )
            return FallbackProcessor.process_fallback(fallback.strategies, tool_call_id, e)

    async def _pre_process_params(self, **kwargs: Any) -> dict[str, Any]:
        for transformer in self.__argument_transformers:
            kwargs = await transformer.transform(kwargs)
        return kwargs

    async def _run_in_stage_report_success(
        self,
        tool_call_id: str,
        stage_wrapper: BaseStageWrapper | None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        params = await self._pre_process_params(**kwargs)
        timer_name = f"tool_{tool_call_id}"
        if stage_wrapper:
            # TODO: filter params ro remove attachment_urls if it's empty
            stage_wrapper.add_parameters(params)
            timer_name = f"tool_{stage_wrapper.name}_{tool_call_id}"
        try:
            self.__perf_timer.start_period(timer_name, 3)
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
            logger.debug(f"Tool call {tool_call_id} finished with result {result}")

            return result
        finally:
            self.__perf_timer.stop_period(timer_name)
