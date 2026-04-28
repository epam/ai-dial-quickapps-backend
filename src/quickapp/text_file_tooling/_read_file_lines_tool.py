from typing import Any

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.text_file_tooling._base_file_tool import _TextFileTool


class _ReadFileLinesTool(_TextFileTool):

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        file_url: str = kwargs["file_url"]
        start_line: int = int(kwargs["start_line"])
        end_line: int = int(kwargs["end_line"])

        if start_line < 0:
            raise InvalidToolCallParameterException("start_line", "start_line must be >= 0")
        if end_line < start_line:
            raise InvalidToolCallParameterException("end_line", "end_line must be >= start_line")

        try:
            file_bytes = await self._dial_file_service.download_file(file_url)
        except ValueError as e:
            raise InvalidToolCallParameterException(
                "file_url", f"file is too large to read (limit: 10 MB): {e}"
            ) from e

        text = file_bytes.decode("utf-8")
        lines = text.splitlines()
        sliced = "\n".join(lines[start_line:end_line])

        result = ToolCallResult(content=sliced, content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
