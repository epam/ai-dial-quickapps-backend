import asyncio
from typing import Any

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.common.utils import fenced_code_block
from quickapp.dial_files_tooling._base_file_tool import _MAX_DEPTH, _DialFileTool
from quickapp.dial_files_tooling._glob import _glob_to_regex
from quickapp.dial_files_tooling._utils import is_root_reference, relative_to

_OUTPUT_MODES = ("content", "files_with_matches")


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

        if self._is_folder_reference(path):
            content = await self._search_folder(
                path=path,
                pattern=pattern,
                context_lines=context_lines,
                case_insensitive=case_insensitive,
                output_mode=self._validate_output_mode(kwargs.get("output_mode")),
                name_filter=kwargs.get("name_filter"),
                max_depth=self._resolve_max_depth(kwargs.get("max_depth"), default=_MAX_DEPTH),
            )
        else:
            content = await self._search_file(
                path=path,
                pattern=pattern,
                context_lines=context_lines,
                case_insensitive=case_insensitive,
            )

        result = ToolCallResult(content=content, content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result

    @staticmethod
    def _is_folder_reference(path: str) -> bool:
        return is_root_reference(path) or path.endswith("/")

    @staticmethod
    def _validate_output_mode(value: Any) -> str:
        output_mode = value or "content"
        if output_mode not in _OUTPUT_MODES:
            raise InvalidToolCallParameterException(
                "output_mode", f"must be one of {', '.join(_OUTPUT_MODES)}"
            )
        return output_mode

    async def _search_file(
        self,
        path: str,
        pattern: str,
        context_lines: int,
        case_insensitive: bool,
    ) -> str:
        url = await self._home_resolver.resolve_appdata_url(path)
        text, _ = await self._download_text(url, display_path=path)
        lines = text.splitlines()
        indices = self._matching_line_indices(lines, pattern, case_insensitive)
        if not indices:
            return "No matches found."
        return fenced_code_block(self._format_matches(lines, indices, context_lines))

    async def _search_folder(
        self,
        path: str,
        pattern: str,
        context_lines: int,
        case_insensitive: bool,
        output_mode: str,
        name_filter: str | None,
        max_depth: int,
    ) -> str:
        folder_url, entries = await self._list_folder_entries(path, max_depth)

        name_regex = _glob_to_regex(name_filter) if name_filter else None
        candidates = [entry for entry in entries if not entry.is_folder]
        if name_regex is not None:
            candidates = [
                entry
                for entry in candidates
                if name_regex.fullmatch(relative_to(entry.url, folder_url))
            ]

        cap = self._dial_files_config.max_files_scanned
        truncated = len(candidates) > cap
        selected = candidates[:cap]
        texts = await asyncio.gather(*(self._read_text_for_scan(entry.url) for entry in selected))

        # (display_path, lines, matching_line_indices) per file with >=1 match.
        matches: list[tuple[str, list[str], list[int]]] = []
        for entry, text in zip(selected, texts):
            if text is None:
                continue
            lines = text.splitlines()
            indices = self._matching_line_indices(lines, pattern, case_insensitive)
            if not indices:
                continue
            display = await self._home_resolver.to_display_path(entry.url)
            matches.append((display, lines, indices))

        body = self._render_folder_output(matches, output_mode, context_lines)
        if truncated:
            body = f"{body}\n{self._truncation_notice(cap)}"
        return body

    @staticmethod
    def _truncation_notice(cap: int) -> str:
        return (
            f"-- search truncated after {cap} files scanned; "
            "narrow with name_filter, a subfolder, or a smaller max_depth --"
        )

    def _render_folder_output(
        self,
        matches: list[tuple[str, list[str], list[int]]],
        output_mode: str,
        context_lines: int,
    ) -> str:
        if not matches:
            return "No matches found."
        if output_mode == "files_with_matches":
            return fenced_code_block("\n".join(display for display, _, _ in matches))
        blocks = [
            f"{display}\n{self._format_matches(lines, indices, context_lines)}"
            for display, lines, indices in matches
        ]
        return fenced_code_block("\n\n".join(blocks))

    @staticmethod
    def _matching_line_indices(lines: list[str], pattern: str, case_insensitive: bool) -> list[int]:
        needle = pattern.lower() if case_insensitive else pattern
        if case_insensitive:
            return [i for i, line in enumerate(lines) if needle in line.lower()]
        return [i for i, line in enumerate(lines) if needle in line]

    @staticmethod
    def _format_matches(lines: list[str], indices: list[int], context_lines: int) -> str:
        merged: list[tuple[int, int]] = []
        for i in indices:
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        parts = [
            "\n".join(f"{n}:{line}" for n, line in enumerate(lines[start:end], start=start + 1))
            for start, end in merged
        ]
        return "\n--\n".join(parts)
