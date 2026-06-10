from typing import Any

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.shared.dial_files._base_file_tool import _DialFileTool


class _SearchInFileTool(_DialFileTool):

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        path: str = kwargs["path"]
        pattern: str = kwargs["pattern"]
        context_lines: int = int(kwargs.get("context_lines") or 0)
        case_insensitive: bool = bool(kwargs.get("case_insensitive", False))

        url = await self._resolve_appdata_url(path)
        text, _ = await self._download_text(url, display_path=path)
        lines = text.splitlines()

        needle = pattern.lower() if case_insensitive else pattern
        haystacks = [line.lower() for line in lines] if case_insensitive else lines

        merged: list[tuple[int, int]] = []
        for i, haystack in enumerate(haystacks):
            if needle not in haystack:
                continue
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        if not merged:
            content = "No matches found."
        else:
            parts = [
                "\n".join(f"{n}:{line}" for n, line in enumerate(lines[start:end], start=start + 1))
                for start, end in merged
            ]
            content = "\n--\n".join(parts)

        result = ToolCallResult(content=content, content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
