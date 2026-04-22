from typing import Any

from aidial_client import DialException
from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult


@inject
class DeploymentStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        stage_params = "> #### Request:\n\r"
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
        if isinstance(exception, DialException):
            return (
                f"> #### Error:\n{exception.message}\n"
                f"> #### Status Code:\n{exception.status_code}\n"
            )
        return "> #### Exception:\nGeneral exception occurred while calling other DIAL deployment\n"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        # For Deployment tools we stream content into choice on the tool execution level
        return ""
