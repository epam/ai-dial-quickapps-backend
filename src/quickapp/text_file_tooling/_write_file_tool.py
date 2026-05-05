from typing import Any

from aidial_client import AsyncDial, EtagMismatchError
from aidial_sdk.chat_completion import Attachment
from injector import AssistedBuilder, inject

from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.config.tools.internal import InternalTool
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.text_file_tooling._base_file_tool import GENERATED_FILES_ROOT, _TextFileTool
from quickapp.text_file_tooling._stage_wrapper import _FileStageWrapper


@inject
class _WriteFileTool(_TextFileTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_FileStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        dial_file_service: DialFileService,
        dial_client: AsyncDial,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,
            tool_config=tool_config,
            perf_timer=perf_timer,
            dial_file_service=dial_file_service,
            argument_transformers=argument_transformers,
            **kwargs,
        )
        self.__dial_client = dial_client

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        filename: str = kwargs["filename"]
        content: str = kwargs["content"]

        self._validate_filename(filename)

        bucket_resp = await self.__dial_client.bucket.get_raw()
        bucket = bucket_resp.appdata or bucket_resp.bucket
        url = f"files/{bucket}/{GENERATED_FILES_ROOT}{filename}"

        try:
            confirmed_url = await self._dial_file_service.upload_text(
                url=url, content=content, if_none_match="*"
            )
        except EtagMismatchError:
            raise InvalidToolCallParameterException("filename", f"file already exists: {url}")

        attachment = Attachment(url=confirmed_url, type="text/plain", title=filename)
        result = ToolCallResult(
            content=f"File written: {confirmed_url}",
            content_type="text/plain",
            attachments=[attachment],
        )
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result

    @staticmethod
    def _validate_filename(filename: str) -> None:
        if not filename or filename != filename.strip():
            raise InvalidToolCallParameterException(
                "filename",
                "filename must be non-empty and have no leading/trailing whitespace",
            )
        if "/" in filename or "\\" in filename:
            raise InvalidToolCallParameterException(
                "filename", "filename must not contain path separators"
            )
        if ".." in filename:
            raise InvalidToolCallParameterException("filename", "filename must not contain '..'")
