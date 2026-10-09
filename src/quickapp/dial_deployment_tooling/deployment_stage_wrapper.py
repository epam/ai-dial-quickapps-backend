from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.common.exception_message_resolver import resolve_exception
from quickapp.common.exceptions import ToolErrorException
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
        # The stage is a user channel: tool errors carry the resolved cause; anything else
        # gets the resolver's curated text, never the raw exception string.
        if isinstance(exception, ToolErrorException):
            return f"> #### Error:\n{exception.user_facing_message}\n"
        return f"> #### Error:\n{resolve_exception(exception).message}\n"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        # For Deployment tools we stream content into choice on the tool execution level
        return ""
