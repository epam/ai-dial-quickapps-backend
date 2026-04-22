from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.text_file_tooling._search_in_file_tool import _SearchInFileTool
from quickapp.text_file_tooling._tool_configs import SEARCH_IN_FILE_TOOL_CONFIG

_SAMPLE = b"alpha\nbeta\ngamma\ndelta\nalpha again"


def _build_tool(file_content: bytes = _SAMPLE) -> _SearchInFileTool:
    dial_file_service = MagicMock()
    dial_file_service.download_file = AsyncMock(return_value=file_content)
    return _SearchInFileTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=SEARCH_IN_FILE_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=dial_file_service,
    )


class TestSearchInFileTool:
    @pytest.mark.asyncio
    async def test_finds_matching_lines(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, file_url="files/f.txt", pattern="alpha"
        )
        assert "1:alpha" in result.content
        assert "5:alpha again" in result.content

    @pytest.mark.asyncio
    async def test_no_match_returns_notice(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, file_url="files/f.txt", pattern="NOTFOUND"
        )
        assert result.content == "No matches found."

    @pytest.mark.asyncio
    async def test_context_lines_includes_surrounding_lines(self):
        tool = _build_tool(b"line0\nline1\nMATCH\nline3\nline4")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, file_url="files/f.txt", pattern="MATCH", context_lines=1
        )
        assert "2:line1" in result.content
        assert "3:MATCH" in result.content
        assert "4:line3" in result.content

    @pytest.mark.asyncio
    async def test_case_insensitive_search(self):
        tool = _build_tool(b"Hello World\ngoodbye")
        result = await tool._run_in_stage_async(
            stage_wrapper=None,
            file_url="files/f.txt",
            pattern="hello",
            case_insensitive=True,
        )
        assert "1:Hello World" in result.content

    @pytest.mark.asyncio
    async def test_case_sensitive_no_match(self):
        tool = _build_tool(b"Hello World\ngoodbye")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, file_url="files/f.txt", pattern="hello"
        )
        assert result.content == "No matches found."

    @pytest.mark.asyncio
    async def test_single_match_has_no_separator(self):
        tool = _build_tool(b"a\nb\nc\nd\ne")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, file_url="files/f.txt", pattern="a"
        )
        assert "--" not in result.content

    @pytest.mark.asyncio
    async def test_non_contiguous_matches_separated(self):
        tool = _build_tool(b"match\nno\nno\nmatch")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, file_url="files/f.txt", pattern="match", context_lines=0
        )
        assert "--" in result.content
        assert "1:match" in result.content
        assert "4:match" in result.content

    @pytest.mark.asyncio
    async def test_content_type_is_text_plain(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, file_url="files/f.txt", pattern="alpha"
        )
        assert result.content_type == "text/plain"
