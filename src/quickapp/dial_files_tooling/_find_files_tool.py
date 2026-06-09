from typing import Any

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.dial_core_services.dial_file_service import FolderEntry
from quickapp.dial_files_tooling._base_file_tool import _MAX_DEPTH, _DialFileTool
from quickapp.dial_files_tooling._glob import _glob_to_regex
from quickapp.dial_files_tooling._utils import relative_to, render_listing


class _FindFilesTool(_DialFileTool):

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        pattern: str = kwargs["pattern"]
        path: str = kwargs.get("path") or ""
        max_depth = self._resolve_max_depth(kwargs.get("max_depth"), default=_MAX_DEPTH)

        regex = _glob_to_regex(pattern)
        folder_url = await self._resolve_folder_url(path)
        entries = await self._list_folder_entries(path, max_depth)

        matched: list[tuple[str, FolderEntry]] = []
        for entry in entries:
            if regex.fullmatch(relative_to(entry.url, folder_url)):
                display = await self._to_display_path(entry.url)
                matched.append((display, entry))

        content = render_listing(matched) if matched else "No files found."

        result = ToolCallResult(content=content, content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
