from typing import Any

from aidial_client._exception import DialException, ResourceNotFoundError

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.dial_core_services.dial_file_service import FolderEntry
from quickapp.dial_files_tooling._base_file_tool import _DialFileTool

_MAX_DEPTH = 10


def _format_size(size: int | None) -> str:
    if size is None:
        return "-"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


def _render_listing(entries: list[tuple[str, FolderEntry]]) -> str:
    if not entries:
        return "(empty folder)"
    name_w = max(len(display) for display, _ in entries)
    name_w = max(name_w, len("NAME"))
    header = f"{'NAME':<{name_w}}  SIZE"
    rows = [header]
    for display, entry in entries:
        size_col = "-" if entry.is_folder else _format_size(entry.size)
        rows.append(f"{display:<{name_w}}  {size_col}")
    return "```\n" + "\n".join(rows) + "\n```"


class _ListFilesTool(_DialFileTool):

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        path: str = kwargs["path"]
        max_depth_raw = kwargs.get("max_depth")
        max_depth: int = int(max_depth_raw) if max_depth_raw is not None else 1

        if max_depth < 1 or max_depth > _MAX_DEPTH:
            raise InvalidToolCallParameterException("max_depth", f"must be in [1, {_MAX_DEPTH}]")

        # Root-of-home references ('', '.', './', '/') list the agent home directory itself.
        # They bypass _resolve_appdata_url, whose validation rejects a leading '/' and would
        # mangle './' into 'files/.../.'.
        if path.strip() in ("", ".", "./", "/"):
            folder_url = await self._resolve_home_dir()
        else:
            if not path.endswith("/"):
                path = path + "/"
            folder_url = await self._resolve_appdata_url(path)

        try:
            home = await self._resolve_home_dir()
        except InvalidToolCallParameterException:
            home = None
        is_home_root = folder_url == home

        try:
            entries = await self._dial_file_service.list_folder(folder_url, max_depth=max_depth)
        except ResourceNotFoundError as e:
            # A 404 on the agent home root means "nothing written yet" → empty listing.
            # A 404 on a user-specified subfolder is a genuine not-found.
            if is_home_root:
                entries = []
            else:
                display = await self._to_display_path(folder_url)
                raise InvalidToolCallParameterException(
                    "path", f"folder not found: {display}"
                ) from e
        except ValueError as e:
            display = await self._to_display_path(folder_url)
            raise InvalidToolCallParameterException("path", f"not a folder: {display}") from e
        except DialException as e:
            self._check_permission_denied(e, path)
            raise

        rendered_entries = [(await self._to_display_path(entry.url), entry) for entry in entries]
        content = _render_listing(rendered_entries)

        result = ToolCallResult(content=content, content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
