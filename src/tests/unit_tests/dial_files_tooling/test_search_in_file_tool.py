from unittest.mock import MagicMock

import pytest

from quickapp.dial_files_tooling._search_in_file_tool import _SearchInFileTool
from quickapp.dial_files_tooling._tool_configs import SEARCH_IN_FILE_TOOL_CONFIG
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_service


def _make_tool(content: str) -> _SearchInFileTool:
    service = make_service()
    service.download_file.return_value = (content.encode("utf-8"), None)
    return _SearchInFileTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=SEARCH_IN_FILE_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=service,
        dial_files_config=make_config(),
    )


class TestSearchInFile:
    @pytest.mark.asyncio
    async def test_relative_path_resolves(self):
        tool = _make_tool("a\nb\nc")
        await tool._run_in_stage_async(stage_wrapper=None, path="x.md", pattern="b")
        tool._dial_file_service.download_file.assert_awaited_once_with("files/appbucket/x.md")

    @pytest.mark.asyncio
    async def test_absolute_path_passes_through(self):
        tool = _make_tool("a\nb\nc")
        await tool._run_in_stage_async(stage_wrapper=None, path="files/o/x.md", pattern="b")
        tool._dial_file_service.download_file.assert_awaited_once_with("files/o/x.md")

    @pytest.mark.asyncio
    async def test_single_match(self):
        tool = _make_tool("foo\nbar\nbaz")
        result = await tool._run_in_stage_async(stage_wrapper=None, path="x", pattern="bar")
        assert result.content == "2:bar"

    @pytest.mark.asyncio
    async def test_no_matches(self):
        tool = _make_tool("foo\nbar")
        result = await tool._run_in_stage_async(stage_wrapper=None, path="x", pattern="zzz")
        assert result.content == "No matches found."

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        tool = _make_tool("Hello\nworld")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="x", pattern="hello", case_insensitive=True
        )
        assert "Hello" in result.content
