from typing import Any

from aidial_client._exception import DialException, ResourceNotFoundError

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.dial_files_tooling._base_file_tool import _DialFileTool

_MAX_DEPTH = 10


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

        if not path.endswith("/"):
            path = path + "/"

        folder_url = await self._resolve_appdata_url(path)

        try:
            entries = await self._dial_file_service.list_folder(folder_url, max_depth=max_depth)
        except ResourceNotFoundError as e:
            raise InvalidToolCallParameterException(
                "path", f"folder not found: {folder_url}"
            ) from e
        except ValueError as e:
            raise InvalidToolCallParameterException("path", f"not a folder: {folder_url}") from e
        except DialException as e:
            self._check_permission_denied(e, path)
            raise

        lines: list[str] = []
        for entry in entries:
            size_col = "-" if entry.is_folder else str(entry.size or 0)
            display = await self._to_display_path(entry.url)
            lines.append(f"{size_col}  {display}")

        content = "\n".join(lines) if lines else "(empty)"
        result = ToolCallResult(content=content, content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
