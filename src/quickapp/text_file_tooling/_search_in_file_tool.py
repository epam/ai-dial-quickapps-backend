from typing import Any

from injector import inject

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.text_file_tooling._base_text_file_tool import _TextFileTool


@inject
class _SearchInFileTool(_TextFileTool):

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        file_url: str = kwargs["file_url"]
        pattern: str = kwargs["pattern"]
        context_lines: int = kwargs.get("context_lines", 0)
        case_insensitive: bool = kwargs.get("case_insensitive", False)

        content_bytes = await self._dial_file_service.download_file(file_url)
        lines = content_bytes.decode("utf-8").splitlines()

        cmp_pattern = pattern.lower() if case_insensitive else pattern
        matching_indices = [
            i
            for i, ln in enumerate(lines)
            if cmp_pattern in (ln.lower() if case_insensitive else ln)
        ]

        if not matching_indices:
            result = ToolCallResult(content="No matches found.", content_type="text/plain")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result

        include_indices: list[int] = sorted(
            {
                i
                for idx in matching_indices
                for i in range(
                    max(0, idx - context_lines), min(len(lines), idx + context_lines + 1)
                )
            }
        )

        output_lines: list[str] = []
        for pos, i in enumerate(include_indices):
            if pos > 0 and include_indices[pos - 1] < i - 1:
                output_lines.append("--")
            output_lines.append(f"{i + 1}:{lines[i]}")

        result = ToolCallResult(content="\n".join(output_lines), content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
