from typing import Any, ClassVar

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.common.chat_completion_stream.argument_stream_presentation import ArgumentStreamMode


@inject
class _PyInterpreterStageWrapper(TimedStageWrapper):
    argument_stream_mode: ClassVar[ArgumentStreamMode | None] = ArgumentStreamMode.CONFIG_MAP

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        return self._render_config_map_parameters(parameters)

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return "> #### Exception:\nGeneral exception occurred while calling other DIAL deployment\n"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return f"> #### Response:\n{result.content}\n"
