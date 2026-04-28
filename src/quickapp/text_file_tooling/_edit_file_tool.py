from typing import Any

from aidial_client._exception import EtagMismatchError

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.text_file_tooling._base_file_tool import _TextFileTool


class _EditFileTool(_TextFileTool):

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        file_url: str = kwargs["file_url"]
        old_string: str = kwargs["old_string"]
        new_string: str = kwargs["new_string"]

        if old_string == new_string:
            raise InvalidToolCallParameterException(
                "new_string", "new_string must differ from old_string"
            )

        file_bytes, etag = await self._dial_file_service.download_file_with_etag(file_url)
        content = file_bytes.decode("utf-8")

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
            await self._dial_file_service.upload_text(
                url=file_url, content=new_content, if_match=etag or None
            )
        except EtagMismatchError:
            raise InvalidToolCallParameterException(
                "file_url", "file changed concurrently; re-read and retry"
            )

        self._dial_file_service.invalidate_cache(file_url)

        result = ToolCallResult(content=f"Edited: {file_url}", content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
