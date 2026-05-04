from typing import Any

from aidial_client import AsyncDial
from aidial_client._exception import ResourceNotFoundError
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
class _DeleteFileTool(_TextFileTool):

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
        file_url: str = kwargs["file_url"]

        if f"/{GENERATED_FILES_ROOT}" not in file_url:
            raise InvalidToolCallParameterException(
                "file_url",
                f"delete is restricted to agent-generated files under {GENERATED_FILES_ROOT}",
            )

        try:
            await self.__dial_client.files.delete(file_url)
        except ResourceNotFoundError:
            raise InvalidToolCallParameterException("file_url", f"file not found: {file_url}")

        result = ToolCallResult(content=f"Deleted: {file_url}", content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
