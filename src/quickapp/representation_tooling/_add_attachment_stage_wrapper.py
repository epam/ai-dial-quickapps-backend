from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.common.utils import filename_from_url_path


@inject
class _AddAttachmentStageWrapper(TimedStageWrapper):

    def _get_stage_title_from_params(self, parameters: dict[str, Any]) -> str:
        title = parameters.get("title")
        url = parameters.get("url") or ""
        name = title or filename_from_url_path(url) or url
        return f" `{name}`" if name else ""

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        return ""

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"### Exception:\n\r{exception}\n\r"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return ""
