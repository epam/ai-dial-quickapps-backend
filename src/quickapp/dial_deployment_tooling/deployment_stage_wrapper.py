from typing import Any

from aidial_client import DialException
from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.common.error_details import (
    MSG_AI_MODEL_RATE_LIMITED,
    RETRY_SENTENCE,
    extract_error_details,
    sanitize_display_message,
)
from quickapp.dial_deployment_tooling.constants import TOOLS_PARAM


@inject
class DeploymentStageWrapper(TimedStageWrapper):
    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        # Parameters without a display config are dumped verbatim into the stage. `tools` is the
        # one that cannot be left to that: it is app configuration rather than a model argument,
        # and its JSON is large enough to bury the actual request. Scalar deployment parameters
        # (temperature, reasoning_effort, ...) stay visible, as they were before static tools.
        visible = {key: value for key, value in parameters.items() if key != TOOLS_PARAM}
        return self._render_config_map_parameters(visible)

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        if isinstance(exception, DialException):
            return (
                f"> #### Error:\n{exception.message}\n"
                f"> #### Status Code:\n{exception.status_code}\n"
            )
        # Backfills the status from `code` for mid-stream errors, which carry no HTTP status.
        details = extract_error_details(exception)
        if details.status_code == 429:
            message = sanitize_display_message(details.display_message or "") or (
                f"{MSG_AI_MODEL_RATE_LIMITED} {RETRY_SENTENCE}"
            )
            return f"> #### Error:\n{message}\n> #### Status Code:\n{details.status_code}\n"
        return "> #### Exception:\nGeneral exception occurred while calling other DIAL deployment\n"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        # For Deployment tools we stream content into choice on the tool execution level
        return ""
