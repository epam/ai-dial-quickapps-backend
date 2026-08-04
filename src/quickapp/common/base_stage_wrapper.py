from abc import ABC, abstractmethod
from types import TracebackType
from typing import Any, ClassVar

from aidial_sdk.chat_completion import Attachment, Stage

from quickapp.common import ToolCallResult
from quickapp.common.chat_completion_stream.argument_stream_presentation import ArgumentStreamMode
from quickapp.common.parameter_stage_format import (
    extract_parameters_config_map,
    render_config_map_parameters,
)
from quickapp.config.tools.base import BaseTool
from quickapp.config.tools.display.paramenter import FormattedParameterConfig


class BaseStageWrapper(ABC):
    # Opt-in: tools whose wrappers set this stream argument bodies into the stage.
    # None = open stage early but keep static add_parameters at execute.
    argument_stream_mode: ClassVar[ArgumentStreamMode | None] = None

    def __init__(
        self,
        stage: Stage,
        tool_config: BaseTool | None = None,
        stage_name: str | None = None,
        *,
        already_open: bool = False,
    ) -> None:
        self.__stage: Stage = stage
        self.__tool_config: BaseTool | None = tool_config
        self.name: str = stage_name if stage_name else ""
        self.__already_open = already_open
        self._parameters_config_map: dict[str, FormattedParameterConfig] = (
            extract_parameters_config_map(tool_config)
        )

    def __enter__(self) -> "BaseStageWrapper":
        if self.__already_open:
            # Stage was opened while tool-call arguments streamed; keep the
            # provisional streaming name and skip Stage.__enter__ / re-open.
            return self
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
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return self.__stage.__exit__(exc_type, exc, traceback)

    def append_stage_name(self, text: str) -> None:
        self.__stage.append_name(text)

    def append_stage_content(self, text: str) -> None:
        self.__stage.append_content(text)

    def add_parameters(self, params: dict[str, Any]) -> None:
        self.append_stage_name(self._get_stage_title_from_params(params))
        self.append_stage_content(self._get_formatted_parameters(params))

    def append_title_from_params(self, params: dict[str, Any]) -> None:
        """Append only the stage-title fragment from params (used when args were pre-streamed)."""
        self.append_stage_name(self._get_stage_title_from_params(params))

    @abstractmethod
    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str: ...

    def add_attachment(self, attachment: Attachment) -> None:
        self.__stage.add_attachment(**attachment.model_dump())

    def add_attachments(self, attachments: list[Attachment]) -> None:
        for attachment in attachments:
            self.add_attachment(attachment)

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

    def _render_config_map_parameters(self, parameters: dict[str, Any]) -> str:
        """Render parameters using the per-parameter display config map.

        Shared building block for wrappers whose tool advertises `display.stage`
        config on its OpenAI parameters. Parameters are ordered by their configured
        `order`, then each is formatted via the shared helpers (or a
        plain `***name:*** value` fallback when it has no display config).
        """
        return render_config_map_parameters(parameters, self._parameters_config_map)

    def add_result(self, result: ToolCallResult) -> None:
        debug_info = self._build_debug_info_from_result(result)
        self.append_stage_content(debug_info)
        if result.attachments:
            for att in result.attachments:
                self.add_attachment(att)

    @abstractmethod
    def _build_debug_info_from_result(self, result: ToolCallResult) -> str: ...
