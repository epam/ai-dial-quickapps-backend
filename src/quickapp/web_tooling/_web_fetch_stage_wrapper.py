from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.common.utils import fenced_code_block
from quickapp.web_tooling._truncation import split_truncation_notice


@inject
class _WebFetchStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        return self._render_config_map_parameters(parameters)

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"### Exception:\n\r{exception}\n\r"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        # A truncated read is composed as notice + blank line + fetched head; show
        # the notice outside the verbatim block so it stays visible however large
        # the head is and is never mistaken for fetched text.
        notice, body = split_truncation_notice(result.content)
        # Fetched content is often itself Markdown/HTML (e.g. a README). Render it
        # inside a fenced code block so the stage shows the fetched text verbatim
        # instead of the UI rendering it as formatted Markdown.
        content_block = f"**Content:**\n{fenced_code_block(body)}\n"
        if notice is None:
            return content_block
        return f"**{notice}**\n\n{content_block}"
