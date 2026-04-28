from typing import Any

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.text_file_tooling._base_file_tool import _TextFileTool


class _SearchInFileTool(_TextFileTool):

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        file_url: str = kwargs["file_url"]
        pattern: str = kwargs["pattern"]
        context_lines: int = int(kwargs.get("context_lines") or 0)
        case_insensitive: bool = bool(kwargs.get("case_insensitive", False))

        try:
            file_bytes = await self._dial_file_service.download_file(file_url)
        except ValueError as e:
            raise InvalidToolCallParameterException(
                "file_url", f"file is too large to read (limit: 10 MB): {e}"
            ) from e

        text = file_bytes.decode("utf-8")
        lines = text.splitlines()

        compare_pattern = pattern.lower() if case_insensitive else pattern

        match_indices = [
            i
            for i, line in enumerate(lines)
            if compare_pattern in (line.lower() if case_insensitive else line)
        ]

        if not match_indices:
            result = ToolCallResult(content="No matches found.", content_type="text/plain")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result

        windows: list[tuple[int, int]] = []
        for idx in match_indices:
            start = max(0, idx - context_lines)
            end = min(len(lines), idx + context_lines + 1)
            windows.append((start, end))

        merged: list[tuple[int, int]] = [windows[0]]
        for start, end in windows[1:]:
            prev_start, prev_end = merged[-1]
            if start <= prev_end:
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))

        output_parts: list[str] = []
        for start, end in merged:
            part_lines = [f"{start + i + 1}:{lines[start + i]}" for i in range(end - start)]
            output_parts.append("\n".join(part_lines))

        content = "\n--\n".join(output_parts)
        result = ToolCallResult(content=content, content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
