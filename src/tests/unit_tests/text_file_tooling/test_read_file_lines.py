from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.text_file_tooling._read_file_lines_tool import _ReadFileLinesTool
from quickapp.text_file_tooling._tool_configs import READ_FILE_LINES_TOOL_CONFIG


def _build_tool(file_content: bytes = b"line0\nline1\nline2\nline3\nline4") -> _ReadFileLinesTool:
    dial_file_service = MagicMock()
    dial_file_service.download_file = AsyncMock(return_value=file_content)
    return _ReadFileLinesTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=READ_FILE_LINES_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=dial_file_service,
    )


class TestReadFileLinesTool:
    @pytest.mark.asyncio
    async def test_returns_correct_slice(self):
        tool = _build_tool(b"line0\nline1\nline2\nline3\nline4")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, file_url="files/f.txt", start_line=1, end_line=3
        )
        assert result.content == "line1\nline2"

    @pytest.mark.asyncio
    async def test_start_at_zero(self):
        tool = _build_tool(b"a\nb\nc")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, file_url="files/f.txt", start_line=0, end_line=2
        )
        assert result.content == "a\nb"

    @pytest.mark.asyncio
    async def test_end_beyond_file_returns_remaining(self):
        tool = _build_tool(b"x\ny\nz")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, file_url="files/f.txt", start_line=1, end_line=1000
        )
        assert result.content == "y\nz"

    @pytest.mark.asyncio
    async def test_negative_start_raises(self):
        tool = _build_tool()
        with pytest.raises(InvalidToolCallParameterException):
            await tool._run_in_stage_async(
                stage_wrapper=None, file_url="files/f.txt", start_line=-1, end_line=3
            )

    @pytest.mark.asyncio
    async def test_end_less_than_start_raises(self):
        tool = _build_tool()
        with pytest.raises(InvalidToolCallParameterException):
            await tool._run_in_stage_async(
                stage_wrapper=None, file_url="files/f.txt", start_line=3, end_line=1
            )

    @pytest.mark.asyncio
    async def test_content_type_is_text_plain(self):
        tool = _build_tool(b"hello")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, file_url="files/f.txt", start_line=0, end_line=1
        )
        assert result.content_type == "text/plain"

    @pytest.mark.asyncio
    async def test_equal_start_end_returns_empty(self):
        tool = _build_tool(b"a\nb\nc")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, file_url="files/f.txt", start_line=1, end_line=1
        )
        assert result.content == ""
