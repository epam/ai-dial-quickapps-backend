from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.text_file_tooling._search_in_file_tool import _SearchInFileTool
from quickapp.text_file_tooling._tool_configs import SEARCH_IN_FILE_TOOL_CONFIG

_FILE = "\n".join(
    [
        "apple pie",  # 0
        "banana split",  # 1
        "cherry tart",  # 2
        "apple turnover",  # 3
        "date pudding",  # 4
    ]
)


def _make_tool(content: str = _FILE) -> _SearchInFileTool:
    mock_service = MagicMock(spec=DialFileService)
    mock_service.download_file = AsyncMock(return_value=content.encode("utf-8"))
    return _SearchInFileTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=SEARCH_IN_FILE_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=mock_service,
    )


class TestSearchInFile:
    @pytest.mark.asyncio
    async def test_single_match_no_context(self):
        tool = _make_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None,
            file_url="files/b/f.txt",
            pattern="cherry",
        )
        assert result.content == "3:cherry tart"
        assert result.content_type == "text/plain"

    @pytest.mark.asyncio
    async def test_no_matches_returns_sentinel(self):
        tool = _make_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None,
            file_url="files/b/f.txt",
            pattern="zzznomatch",
        )
        assert result.content == "No matches found."

    @pytest.mark.asyncio
    async def test_multiple_matches(self):
        tool = _make_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None,
            file_url="files/b/f.txt",
            pattern="apple",
        )
        lines = result.content.split("\n")
        assert "1:apple pie" in lines
        assert "4:apple turnover" in lines

    @pytest.mark.asyncio
    async def test_context_lines_included(self):
        tool = _make_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None,
            file_url="files/b/f.txt",
            pattern="cherry",
            context_lines=1,
        )
        assert "2:banana split" in result.content
        assert "3:cherry tart" in result.content
        assert "4:apple turnover" in result.content

    @pytest.mark.asyncio
    async def test_non_adjacent_windows_separated_by_dashes(self):
        tool = _make_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None,
            file_url="files/b/f.txt",
            pattern="apple",
            context_lines=0,
        )
        assert "--" in result.content

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        tool = _make_tool("Hello World\ngoodbye world")
        result = await tool._run_in_stage_async(
            stage_wrapper=None,
            file_url="files/b/f.txt",
            pattern="hello",
            case_insensitive=True,
        )
        assert "Hello World" in result.content

    @pytest.mark.asyncio
    async def test_case_sensitive_by_default(self):
        tool = _make_tool("Hello World\ngoodbye world")
        result = await tool._run_in_stage_async(
            stage_wrapper=None,
            file_url="files/b/f.txt",
            pattern="hello",
        )
        assert result.content == "No matches found."

    @pytest.mark.asyncio
    async def test_large_file_raises_invalid_parameter(self):
        mock_service = MagicMock(spec=DialFileService)
        mock_service.download_file = AsyncMock(
            side_effect=ValueError("File size exceeds the limit")
        )
        tool = _SearchInFileTool(
            stage_wrapper_builder=MagicMock(),
            tool_config=SEARCH_IN_FILE_TOOL_CONFIG,
            perf_timer=MagicMock(),
            dial_file_service=mock_service,
        )
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None,
                file_url="files/b/huge.txt",
                pattern="x",
            )
        assert exc.value.parameter_name == "file_url"
        assert "File download failed:" in exc.value.message
