from typing import Any

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.dial_files_tooling._base_file_tool import _DialFileTool


class _ReadFileLinesTool(_DialFileTool):

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        path: str = kwargs["path"]
        start_line: int = int(kwargs["start_line"])
        end_line: int = int(kwargs["end_line"])

        if start_line < 0:
            raise InvalidToolCallParameterException("start_line", "start_line must be >= 0")
        if end_line < start_line:
            raise InvalidToolCallParameterException("end_line", "end_line must be >= start_line")

        url = await self._home_resolver.resolve_appdata_url(path)
        text, _ = await self._download_text(url, display_path=path)
        lines = text.splitlines()
        sliced = "\n".join(lines[start_line:end_line])

        result = ToolCallResult(content=sliced, content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
