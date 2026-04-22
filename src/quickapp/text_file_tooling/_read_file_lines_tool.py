from typing import Any

from injector import AssistedBuilder, inject

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.config.tools.internal import InternalTool
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.text_file_tooling._stage_wrapper import _TextFileStageWrapper


@inject
class _ReadFileLinesTool(StagedBaseTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_TextFileStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        dial_file_service: DialFileService,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            **kwargs,
        )
        self._dial_file_service = dial_file_service

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        file_url: str = kwargs["file_url"]
        start_line: int = kwargs["start_line"]
        end_line: int = kwargs["end_line"]

        if start_line < 0:
            raise InvalidToolCallParameterException(
                "start_line",
                f"start_line must be >= 0, got {start_line}",
            )
        if end_line < start_line:
            raise InvalidToolCallParameterException(
                "end_line",
                f"end_line ({end_line}) must be >= start_line ({start_line})",
            )

        content_bytes = await self._dial_file_service.download_file(file_url)
        lines = content_bytes.decode("utf-8").splitlines()
        content = "\n".join(lines[start_line:end_line])

        result = ToolCallResult(content=content, content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
