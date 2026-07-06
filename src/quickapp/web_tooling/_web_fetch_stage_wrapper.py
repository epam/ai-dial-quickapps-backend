from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.common.utils import fenced_code_block


@inject
class _WebFetchStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        return self._render_config_map_parameters(parameters)

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"### Exception:\n\r{exception}\n\r"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        # Fetched content is often itself Markdown/HTML (e.g. a README). Render it
        # inside a fenced code block so the stage shows the fetched text verbatim
        # instead of the UI rendering it as formatted Markdown.
        return f"**Content:**\n{fenced_code_block(result.content)}\n"
