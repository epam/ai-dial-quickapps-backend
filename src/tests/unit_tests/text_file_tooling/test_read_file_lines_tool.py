from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.text_file_tooling._read_file_lines_tool import _ReadFileLinesTool
from quickapp.text_file_tooling._tool_configs import READ_FILE_LINES_TOOL_CONFIG


def _make_tool(file_content: bytes = b"line0\nline1\nline2\nline3\nline4") -> _ReadFileLinesTool:
    mock_service = MagicMock(spec=DialFileService)
    mock_service.download_file = AsyncMock(return_value=file_content)
    return _ReadFileLinesTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=READ_FILE_LINES_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=mock_service,
    )


class TestReadFileLines:
    @pytest.mark.asyncio
    async def test_returns_requested_slice(self):
        tool = _make_tool(b"line0\nline1\nline2\nline3\nline4")
        result = await tool._run_in_stage_async(
            stage_wrapper=None,
            file_url="files/b/f.txt",
            start_line=1,
            end_line=3,
        )
        assert result.content == "line1\nline2"
        assert result.content_type == "text/plain"

    @pytest.mark.asyncio
    async def test_start_equals_end_returns_empty(self):
        tool = _make_tool(b"line0\nline1")
        result = await tool._run_in_stage_async(
            stage_wrapper=None,
            file_url="files/b/f.txt",
            start_line=1,
            end_line=1,
        )
        assert result.content == ""

    @pytest.mark.asyncio
    async def test_end_beyond_file_clamps(self):
        tool = _make_tool(b"only\ntwo")
        result = await tool._run_in_stage_async(
            stage_wrapper=None,
            file_url="files/b/f.txt",
            start_line=0,
            end_line=100,
        )
        assert result.content == "only\ntwo"

    @pytest.mark.asyncio
    async def test_negative_start_line_raises(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None,
                file_url="files/b/f.txt",
                start_line=-1,
                end_line=3,
            )
        assert exc.value.parameter_name == "start_line"

    @pytest.mark.asyncio
    async def test_end_before_start_raises(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None,
                file_url="files/b/f.txt",
                start_line=5,
                end_line=2,
            )
        assert exc.value.parameter_name == "end_line"

    @pytest.mark.asyncio
    async def test_large_file_raises_invalid_parameter(self):
        mock_service = MagicMock(spec=DialFileService)
        mock_service.download_file = AsyncMock(
            side_effect=ValueError("File size 11534336 exceeds the limit")
        )
        tool = _ReadFileLinesTool(
            stage_wrapper_builder=MagicMock(),
            tool_config=READ_FILE_LINES_TOOL_CONFIG,
            perf_timer=MagicMock(),
            dial_file_service=mock_service,
        )
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None,
                file_url="files/b/huge.txt",
                start_line=0,
                end_line=10,
            )
        assert exc.value.parameter_name == "file_url"
        assert "File download failed:" in exc.value.message
        assert "11534336" in exc.value.message
