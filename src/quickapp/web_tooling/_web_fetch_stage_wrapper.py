from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.common.exceptions import ToolErrorException
from quickapp.common.utils import fenced_code_block
from quickapp.web_tooling._truncation import split_truncation_notice


@inject
class _WebFetchStageWrapper(TimedStageWrapper):
    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        return self._render_config_map_parameters(parameters)

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        if isinstance(exception, ToolErrorException):
            return f"> ##### Error:\n{exception.user_facing_message}\n"
        return f"### Exception:\n\r{exception}\n\r"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        # Render any truncation notice outside the verbatim block so it stays
        # visible; render the fetched text (often Markdown/HTML) fenced so the UI
        # shows it verbatim instead of formatting it.
        notice, body = split_truncation_notice(result.content)
        content_block = f"**Content:**\n{fenced_code_block(body)}\n"
        if notice is None:
            return content_block
        return f"**{notice}**\n\n{content_block}"
