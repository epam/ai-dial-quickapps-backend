from typing import Any

from aidial_client._exception import DialException, EtagMismatchError
from aidial_sdk.chat_completion import Attachment

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.dial_files_tooling._base_file_tool import _DialFileTool


class _WriteFileTool(_DialFileTool):

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        path: str = kwargs["path"]
        content: str = kwargs["content"]
        content_type: str = kwargs.get("content_type") or "text/plain"
        overwrite: bool = bool(kwargs.get("overwrite", False))

        self._reject_absolute_path("path", "write_file", path)

        url = await self._resolve_appdata_url(path)
        display_path = await self._to_display_path(url)

        try:
            await self._dial_file_service.write_file(
                url=url,
                content=content,
                content_type=content_type,
                overwrite=overwrite,
            )
        except EtagMismatchError as e:
            raise InvalidToolCallParameterException(
                "path",
                f"file already exists: {display_path}. Ask the user whether to replace it; "
                "only if they approve, retry with overwrite=True.",
            ) from e
        except DialException as e:
            self._check_permission_denied(e, display_path)
            raise

        attachment = Attachment(url=url, type=content_type, title=display_path)
        result = ToolCallResult(
            content=f"File written: {display_path}",
            content_type="text/plain",
            attachments=[attachment],
        )
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
