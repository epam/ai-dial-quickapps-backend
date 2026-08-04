from typing import Any, ClassVar

from aidial_client import DialException
from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.common.chat_completion_stream.argument_stream_presentation import ArgumentStreamMode


@inject
class DeploymentStageWrapper(TimedStageWrapper):
    argument_stream_mode: ClassVar[ArgumentStreamMode | None] = ArgumentStreamMode.CONFIG_MAP

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        return self._render_config_map_parameters(parameters)

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        if isinstance(exception, DialException):
            return (
                f"> #### Error:\n{exception.message}\n"
                f"> #### Status Code:\n{exception.status_code}\n"
            )
        return "> #### Exception:\nGeneral exception occurred while calling other DIAL deployment\n"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        # For Deployment tools we stream content into choice on the tool execution level
        return ""
