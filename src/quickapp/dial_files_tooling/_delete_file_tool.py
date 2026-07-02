from typing import Any

from aidial_client._exception import DialException, ResourceNotFoundError

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.dial_files_tooling._base_file_tool import _DialFileTool
from quickapp.dial_files_tooling._utils import reject_absolute_path


class _DeleteFileTool(_DialFileTool):

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        path: str = kwargs["path"]

        reject_absolute_path("path", "delete_file", path)
        url = await self._home_resolver.resolve_appdata_url(path)
        display_path = await self._home_resolver.to_display_path(url)

        try:
            await self._dial_file_service.delete(url)
        except ResourceNotFoundError as e:
            raise InvalidToolCallParameterException("path", f"file not found: {path}") from e
        except DialException as e:
            self._check_permission_denied(e, display_path)
            raise

        result = ToolCallResult(content=f"Deleted: {display_path}", content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
