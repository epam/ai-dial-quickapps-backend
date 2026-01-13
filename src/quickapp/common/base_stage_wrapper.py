from abc import ABC, abstractmethod
from types import TracebackType
from typing import Any, Optional, Type, cast

from aidial_sdk.chat_completion import Attachment, Stage

from quickapp.config.tools.base import BaseOpenAITool, BaseTool
from quickapp.config.tools.display.paramenter import (
    FormattedParameterConfig,
    ParameterDisplayConfig,
)

from . import CompletionResult


class BaseStageWrapper(ABC):

    def __init__(
        self, stage: Stage, tool_config: Optional[BaseTool] = None, stage_name: Optional[str] = None
    ) -> None:
        self.__stage: Stage = stage
        self.__tool_config: BaseTool | None = tool_config
        self.name: str = stage_name if stage_name else ""
        self._parameters_config_map: dict[str, FormattedParameterConfig] = {}
        if tool_config and issubclass(type(tool_config), BaseOpenAITool):
            openai_tool_config = cast(Type[BaseOpenAITool], tool_config)
            for (
                prop_name,
                config,
            ) in openai_tool_config.open_ai_tool.function.parameters.properties.items():
                display_conf: ParameterDisplayConfig = config.display
                if display_conf and display_conf.stage:
                    self._parameters_config_map[prop_name] = display_conf.stage

    def __enter__(self) -> "BaseStageWrapper":
        self.__stage.__enter__()
        self.__stage.append_name(self._get_display_name())
        return self

    def _get_display_name(self) -> str:
        display_name = ""
        if self.__tool_config:
            if self.__tool_config.display:
                display_config = self.__tool_config.display
                if (
                    display_config
                    and display_config.stage
                    and display_config.stage.show
                    and display_config.stage.name
                ):
                    display_name = display_config.stage.name
                elif self.name:
                    display_name = self.name
            elif hasattr(self.__tool_config, "open_ai_tool"):
                display_name = (
                    f"Calling {self.__tool_config.open_ai_tool.function.name} application"
                )

        if not display_name and self.name:
            display_name = self.name

        return display_name

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> Optional[bool]:
        return self.__stage.__exit__(exc_type, exc, traceback)

    def append_stage_name(self, text: str) -> None:
        self.__stage.append_name(text)

    def append_stage_content(self, text: str) -> None:
        self.__stage.append_content(text)

    def add_parameters(self, params: dict[str, Any]) -> None:
        self.append_stage_name(self._get_stage_title_from_params(params))
        self.append_stage_content(self._get_formatted_parameters(params))

    @abstractmethod
    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str: ...

    def add_stage_attachment(self, attachment: Attachment) -> None:
        self.__stage.add_attachment(**attachment.model_dump())

    def add_stage_attachments(self, attachments: list[Attachment]) -> None:
        for attachment in attachments:
            self.add_stage_attachment(attachment)

    def add_exception(self, exception: Exception) -> None:
        debug_info = self._build_debug_info_from_exception(exception)
        self.append_stage_content(debug_info)

    @abstractmethod
    def _build_debug_info_from_exception(self, exception: Exception) -> str: ...

    def _get_stage_title_from_params(self, parameters: dict[str, Any]) -> str:
        title = ""

        for param_name, param_value in parameters.items():
            if display_config := self._parameters_config_map.get(param_name):
                if display_config.show_value_in_stage_title:
                    param_str = str(param_value)
                    title = param_str
                    break

        return title

    def _get_parameter_name(self, param_name: str, display_config: FormattedParameterConfig) -> str:
        if display_config.name:
            return display_config.name
        elif display_config.ignore_parameter_name:
            return ""
        return f"***{param_name}:*** "

    def _get_value_prefix(self, display_config: FormattedParameterConfig) -> str:
        return display_config.prefix if display_config.prefix else ""

    def _get_value_sufix(self, display_config: FormattedParameterConfig) -> str:
        return display_config.suffix if display_config.suffix else ""

    def _get_parameter_value(
        self, param_value: Any, display_config: FormattedParameterConfig
    ) -> str:
        result_value = (
            display_config.replaced_value_info
            if display_config.replaced_value_info
            else param_value
        )

        if display_config.format:
            result_value = f"\n```{display_config.format}\n{result_value}\n\n```"

        return str(result_value)

    def add_result(self, result: CompletionResult) -> None:
        debug_info = self._build_debug_info_from_result(result)
        self.append_stage_content(debug_info)
        if result.attachments:
            for att in result.attachments:
                self.add_stage_attachment(att)

    @abstractmethod
    def _build_debug_info_from_result(self, result: CompletionResult) -> str: ...
