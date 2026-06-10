from typing import Any

from aidial_client._exception import DialException, EtagMismatchError

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.shared.dial_files._base_file_tool import _DialFileTool


class _EditFileTool(_DialFileTool):

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        path: str = kwargs["path"]
        old_string: str = kwargs["old_string"]
        new_string: str = kwargs["new_string"]

        if old_string == new_string:
            raise InvalidToolCallParameterException(
                "new_string", "new_string must differ from old_string"
            )

        self._reject_absolute_path("path", "edit_file", path)
        url = await self._resolve_appdata_url(path)
        display_path = await self._to_display_path(url)

        content, metadata = await self._download_text(url, display_path=path)
        etag = metadata.etag if metadata else None

        count = content.count(old_string)
        if count == 0:
            raise InvalidToolCallParameterException("old_string", "old_string not found in file")
        if count > 1:
            raise InvalidToolCallParameterException(
                "old_string",
                f"old_string found {count} times; provide more surrounding context to disambiguate",
            )

        new_content = content.replace(old_string, new_string, 1)

        try:
            await self._dial_file_service.write_file(url=url, content=new_content, if_match=etag)
        except EtagMismatchError as e:
            raise InvalidToolCallParameterException(
                "path", "file changed concurrently; re-read and retry"
            ) from e
        except DialException as e:
            self._check_permission_denied(e, display_path)
            raise

        result = ToolCallResult(content=f"Edited: {display_path}", content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
