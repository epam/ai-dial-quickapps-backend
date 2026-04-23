from typing import Any

from injector import inject

from quickapp.common.timed_stage_wrapper import TimedStageWrapper
from quickapp.common.tool_call_result import ToolCallResult


@inject
class _TextFileStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        stage_params = "> #### Params:\n\r"
        for param_name, param_value in parameters.items():
            if display_config := self._parameters_config_map.get(param_name):
                if not display_config.ignore:
                    stage_params += self._get_parameter_name(param_name, display_config)
                    stage_params += self._get_value_prefix(display_config)
                    stage_params += self._get_parameter_value(param_value, display_config)
                    stage_params += self._get_value_sufix(display_config)
                    stage_params += "\n\r"
            else:
                stage_params += f"***{param_name}:*** {param_value}\n\r"
        return stage_params

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"##### Exception:\n{type(exception).__name__}: {exception}\n"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        if not result.content:
            return ""
        return f"> #### Content:\n```\n{result.content}\n```\n"
