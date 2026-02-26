import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Optional

from injector import AssistedBuilder
from pydantic import BaseModel, Field

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.config.tools.base import BaseTool as _BaseToolConfig
from quickapp.config.tools.tool_fallback import RetryStrategyModel
from quickapp.dial_core_services.dial_file_service import DialFileService

from ._file_prefix_handlers import FilePrefixHandlers
from .completion_result import CompletionResult
from .exceptions import InvalidToolCallParameterException
from .perf_timer.perf_timer import PerformanceTimer
from .tool_fallback.processor import FallbackProcessor
from .utils import matches_type

logger = logging.getLogger(__name__)

FILE_PATTERN = re.compile(
    r'^/*file:(?:(?P<prefix>base64|url|text)::)?(?P<file_url>.+)$', re.IGNORECASE
)


class StagedBaseTool(ABC, BaseModel, extra='allow'):
    stage_name_component: Optional[str] = Field(None)

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[BaseStageWrapper],
        perf_timer: PerformanceTimer,
        tool_config: _BaseToolConfig,
        file_service: (
            DialFileService | None
        ) = None,  # file_service is optional to avoid breaking existing tools that don't need it, but can be used for any tool that needs to handle file parameters
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.__stage_wrapper_builder: AssistedBuilder[BaseStageWrapper] = stage_wrapper_builder
        self._tool_config: _BaseToolConfig = tool_config
        self.__perf_timer: PerformanceTimer = perf_timer
        self.__file_service: DialFileService | None = file_service

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
        display = self._tool_config.display
        if display and display.stage and not display.stage.show:
            return await self._run_in_stage_report_success(tool_call_id, None, *args, **kwargs)

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
                fallback = self._tool_config.fallback_configuration
                if fallback.display_error_in_stage:
                    stage_wrapper.add_exception(e)
                else:
                    stage_wrapper.add_exception(
                        Exception("An error occurred while executing the tool.")
                    )
                return FallbackProcessor.process_fallback(fallback.strategies, tool_call_id, e)

    async def _handle_base64_prefix(self, key: str, file_url: str) -> str:
        """Handle base64 prefix for file parameters. Can be overridden in derived classes."""
        logger.debug(
            "Detected 'base64' prefix for key %s (url: %s) - placeholder handling",
            key,
            file_url,
        )
        if self.__file_service is None:
            logger.error(
                f"DialFileService is None, cannot process base64 file for key {key} with url {file_url}"
            )
            raise InvalidToolCallParameterException(
                parameter_name=key,
                message=f"DialFileService is None, cannot process base64 file for key {key} with url {file_url}",
            )
        return await FilePrefixHandlers.handle_base64(file_url, self.__file_service)

    async def _handle_url_prefix(self, key: str, file_url: str) -> str:
        """Handle url prefix for file parameters. Can be overridden in derived classes."""
        logger.debug(
            "Detected 'url' prefix for key %s (url: %s) - placeholder handling",
            key,
            file_url,
        )
        return file_url

    async def _handle_text_prefix(self, key: str, file_url: str) -> str:
        """Handle text prefix for file parameters. Can be overridden in derived classes."""
        logger.debug(
            "Detected 'text' prefix for key %s (text: %s) - placeholder handling",
            key,
            file_url,
        )
        if self.__file_service is None:
            logger.error(
                f"DialFileService is None, cannot process text file for key {key} with url {file_url}"
            )
            raise InvalidToolCallParameterException(
                parameter_name=key,
                message=f"DialFileService is None, cannot process text file for key {key} with url {file_url}",
            )
        return await FilePrefixHandlers.handle_text(
            file_url, self.__file_service, parameter_name=key
        )

    async def _handle_no_prefix(self, key: str, value: str) -> str:
        """Handle file references without prefix. Can be overridden in derived classes."""
        logger.warning("Detected file reference without prefix for key %s (value: %s)", key, value)
        raise InvalidToolCallParameterException(
            parameter_name=key,
            message="Missing required file prefix (base64::, url::, text::)",
        )

    async def _process_file_parameter(self, key: str, value: str) -> str:
        """Process a single file parameter value that matches the file pattern."""
        m = FILE_PATTERN.match(value)
        if not m:
            return value

        detected_prefix = m.group("prefix").lower() if m.group("prefix") else None
        file_url_part = m.group("file_url")

        if detected_prefix == "base64":
            return await self._handle_base64_prefix(key, file_url_part)
        elif detected_prefix == "url":
            return await self._handle_url_prefix(key, file_url_part)
        elif detected_prefix == "text":
            return await self._handle_text_prefix(key, file_url_part)
        else:
            return await self._handle_no_prefix(key, value)

    async def _process_parameter_value(self, key: str, value: Any) -> Any:
        """Process a parameter value - handles both strings and lists of strings."""
        if isinstance(value, str):
            return await self._process_file_parameter(key, value)
        elif isinstance(value, list):
            processed_list = (
                []
            )  # todo: if first item is not str do we need to process other items in the list?
            for item in value:
                if isinstance(item, str):
                    processed_list.append(await self._process_file_parameter(key, item))
                else:
                    processed_list.append(item)
            return processed_list
        else:
            return value

    async def _pre_process_params(self, **kwargs: Any) -> Any:
        for key, value in list(kwargs.items()):
            if not isinstance(value, str) and not isinstance(value, list):
                continue
            kwargs[key] = await self._process_parameter_value(key, value)

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
            result.tool_call_id = tool_call_id
            if result.attachments:
                attachment_cfg = self._tool_config.attachment
                filtered: list = []
                for a in result.attachments:
                    if matches_type(a.type, attachment_cfg.supported_types):
                        filtered.append(a)
                        if matches_type(a.type, attachment_cfg.propagate_types_to_choice):
                            result.propagate_to_choice.append(a)
                result.attachments = filtered
            logger.debug(f"Tool call {tool_call_id} finished with result {result}")

            return result
        finally:
            self.__perf_timer.stop_period(timer_name)
