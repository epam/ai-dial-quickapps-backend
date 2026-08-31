from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.common.utils import fenced_code_block


@inject
class _SkillReaderStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        # `skill_name` is rendered into the stage *title*, so a manifest read has
        # no parameter left to show. Rendering anyway would leave a bare
        # "Request:" header over nothing on the most common call.
        if not parameters.get("file_path", "").strip():
            return ""
        return self._render_config_map_parameters(parameters)

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"#### Error:\n{fenced_code_block(str(exception))}\n"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return f"#### Skill Content:\n{fenced_code_block(result.content)}\n"
