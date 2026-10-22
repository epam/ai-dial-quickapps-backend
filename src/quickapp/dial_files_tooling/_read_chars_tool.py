from typing import Any

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.dial_files_tooling._base_file_tool import _DialFileTool
from quickapp.dial_files_tooling._utils import MAX_OUTPUT_CHARS


class _ReadCharsTool(_DialFileTool):

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        path: str = kwargs["path"]
        offset: int = int(kwargs["offset"])
        length: int = int(kwargs["length"])

        if offset < 0:
            raise InvalidToolCallParameterException("offset", "offset must be >= 0")
        if length < 1:
            raise InvalidToolCallParameterException("length", "length must be >= 1")

        url = await self._home_resolver.resolve_appdata_url(path)
        text, _ = await self._download_text(url, display_path=path)
        total = len(text)
        if offset > total:
            raise InvalidToolCallParameterException(
                "offset", f"offset is beyond the end of the file ({total} characters)"
            )

        effective_length = min(length, MAX_OUTPUT_CHARS)
        end = min(offset + effective_length, total)
        footer = self._footer(offset, end, total, limited=length > MAX_OUTPUT_CHARS)

        result = ToolCallResult(content=f"{text[offset:end]}\n{footer}", content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result

    @staticmethod
    def _footer(offset: int, end: int, total: int, limited: bool) -> str:
        parts = [f"chars {offset}-{end} of {total}"]
        if limited:
            parts.append(f"length limited to {MAX_OUTPUT_CHARS}")
        parts.append("end of file" if end >= total else f"next offset: {end}")
        return f"-- {'; '.join(parts)} --"
