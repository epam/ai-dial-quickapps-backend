from typing import Any

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.dial_files_tooling._base_file_tool import _DialFileTool
from quickapp.dial_files_tooling._utils import render_listing


class _ListFilesTool(_DialFileTool):

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        path: str = kwargs["path"]
        max_depth = self._resolve_max_depth(kwargs.get("max_depth"), default=1)

        _, entries = await self._list_folder_entries(path, max_depth)

        rendered_entries = [(await self._to_display_path(entry.url), entry) for entry in entries]
        content = render_listing(rendered_entries)

        result = ToolCallResult(content=content, content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
