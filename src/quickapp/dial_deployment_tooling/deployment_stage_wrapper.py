from typing import Any

import openai
from aidial_client import DialException
from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.dial_deployment_tooling.constants import TOOLS_PARAM

# Mirrors the top-level resolver wording for the same 429.
_RATE_LIMITED_MESSAGE = (
    "The request was rate-limited by the AI model service. Please try again later."
)


def _extract_display_message(body: object) -> str | None:
    # DIAL Core nests error fields under "error"; display_message is user-safe by contract.
    if not isinstance(body, dict):
        return None
    inner = body.get("error", body)
    if not isinstance(inner, dict):
        return None
    display_message = inner.get("display_message")
    if not isinstance(display_message, str):
        return None
    return display_message.strip() or None


def _status_code(exception: openai.APIError) -> int | None:
    # Mid-stream errors carry no HTTP status; DIAL puts it in the body's `code` instead.
    status_code = getattr(exception, "status_code", None)
    if status_code is not None or not isinstance(exception.body, dict):
        return status_code
    inner = exception.body.get("error", exception.body)
    code = str(inner.get("code")) if isinstance(inner, dict) else ""
    return int(code) if code.isdigit() else None


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
        if isinstance(exception, openai.APIError) and _status_code(exception) == 429:
            message = _extract_display_message(exception.body) or _RATE_LIMITED_MESSAGE
            return f"> #### Error:\n{message}\n> #### Status Code:\n429\n"
        return "> #### Exception:\nGeneral exception occurred while calling other DIAL deployment\n"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        # For Deployment tools we stream content into choice on the tool execution level
        return ""
