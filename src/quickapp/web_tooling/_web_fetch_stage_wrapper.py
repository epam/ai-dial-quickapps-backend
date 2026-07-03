from typing import Any

from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult


@inject
class _WebFetchStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        url = parameters.get("url")
        return f"`{url}`" if url else ""

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"### Exception:\n\r{exception}\n\r"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return f"### Fetched content:\n\r{result.content}\n\r"
