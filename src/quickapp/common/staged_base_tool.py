import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from injector import AssistedBuilder
from pydantic import BaseModel, Field

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.config.tools.base import BaseTool as _BaseToolConfig
from quickapp.config.tools.tool_fallback import RetryStrategyModel

from .completion_result import CompletionResult
from .exceptions import InvalidToolCallParameterException
from .perf_timer.perf_timer import PerformanceTimer
from .tool_fallback.processor import FallbackProcessor
from .utils import matches_type

logger = logging.getLogger(__name__)


class StagedBaseTool(ABC, BaseModel, extra='allow'):
    stage_name_component: Optional[str] = Field(None)

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[BaseStageWrapper],
        perf_timer: PerformanceTimer,
        tool_config: _BaseToolConfig,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.__stage_wrapper_builder: AssistedBuilder[BaseStageWrapper] = stage_wrapper_builder
        self._tool_config: _BaseToolConfig = tool_config
        self.__perf_timer: PerformanceTimer = perf_timer

    @property
    def tool_config(self):
        return self._tool_config

    @abstractmethod  # pragma: no cover
    async def _run_in_stage_async(
        self, stage_wrapper: Optional[BaseStageWrapper], *args: Any, **kwargs: Any
    ) -> CompletionResult: ...

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Use only async version")

    async def arun(self, tool_call_id: str, *args: Any, **kwargs: Any) -> CompletionResult:
        if (
            self._tool_config
            and self._tool_config.display
            and self._tool_config.display.stage
            and not self._tool_config.display.stage.show
        ):
            return await self._run_in_stage_report_success(tool_call_id, None, *args, **kwargs)
        else:
            stage_wrapper = self.__stage_wrapper_builder.build(
                tool_config=self._tool_config,
                stage_name=self.stage_name_component,
            )
            with stage_wrapper:
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
                    if (
                        self._tool_config
                        and self._tool_config.fallback_configuration
                        and self._tool_config.fallback_configuration.display_error_in_stage
                    ):
                        stage_wrapper.add_exception(e)
                    else:
                        stage_wrapper.add_exception(
                            Exception("An error occurred while executing the tool.")
                        )
                    if self._tool_config and self._tool_config.fallback_configuration:
                        return FallbackProcessor.process_fallback(
                            self._tool_config.fallback_configuration.strategies, tool_call_id, e
                        )
                    raise e

    async def _pre_process_params(self, **kwargs: Any) -> Any:
        # No preprocessing of parameters by default. return parameters "as is"
        return kwargs

    async def _run_in_stage_report_success(
        self,
        tool_call_id: str,
        stage_wrapper: Optional[BaseStageWrapper],
        *args: Any,
        **kwargs: Any,
    ) -> CompletionResult:
        params = await self._pre_process_params(**kwargs)
        timer_name = f"tool_{tool_call_id}"
        if stage_wrapper:
            # TODO: filter params ro remove attachment_urls if it's empty
            stage_wrapper.add_parameters(params)
            timer_name = f"tool_{stage_wrapper.name}_{tool_call_id}"
        try:
            self.__perf_timer.start_period(timer_name, 3)
            result: CompletionResult = await self._run_in_stage_async(
                stage_wrapper, *args, **params
            )
            result.tool_call_id = tool_call_id  # Set result as response to specific tool call.
            # filter attachments to fit only supported_attachments
            if result.attachments:
                filtered_attachments = []
                for a in result.attachments:
                    if matches_type(a.type, self._tool_config.attachment.supported_types):
                        filtered_attachments.append(a)
                    if matches_type(a.type, self._tool_config.attachment.propagate_types_to_choice):
                        result.propagate_to_choice.append(a)
                result.attachments = filtered_attachments
            logger.debug(f"Tool call {tool_call_id} finished with result {result}")

            return result
        finally:
            self.__perf_timer.stop_period(timer_name)
