from unittest.mock import MagicMock

import pytest

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_files_tooling._read_file_lines_tool import _ReadFileLinesTool
from quickapp.dial_files_tooling._tool_configs import READ_FILE_LINES_TOOL_CONFIG
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_dial_client, make_service


def _make_tool(content: bytes = b"a\nb\nc\nd\ne") -> _ReadFileLinesTool:
    service = make_service()
    service.download_file.return_value = (content, None)
    return _ReadFileLinesTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=READ_FILE_LINES_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=service,
        dial_client=make_dial_client(),
        dial_files_config=make_config(),
    )


class TestReadFileLines:
    @pytest.mark.asyncio
    async def test_relative_path_resolves_under_home(self):
        tool = _make_tool()
        await tool._run_in_stage_async(
            stage_wrapper=None, path="reports/x.md", start_line=0, end_line=2
        )
        tool._dial_file_service.download_file.assert_awaited_once_with(
            "files/appbucket/reports/x.md"
        )

    @pytest.mark.asyncio
    async def test_absolute_path_passes_through(self):
        tool = _make_tool()
        await tool._run_in_stage_async(
            stage_wrapper=None,
            path="files/other/uploads/notes.txt",
            start_line=0,
            end_line=2,
        )
        tool._dial_file_service.download_file.assert_awaited_once_with(
            "files/other/uploads/notes.txt"
        )

    @pytest.mark.asyncio
    async def test_returns_requested_slice(self):
        tool = _make_tool(b"line0\nline1\nline2\nline3")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="f.txt", start_line=1, end_line=3
        )
        assert result.content == "line1\nline2"

    @pytest.mark.asyncio
    async def test_negative_start_raises(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, path="f.txt", start_line=-1, end_line=2
            )
        assert exc.value.parameter_name == "start_line"

    @pytest.mark.asyncio
    async def test_end_before_start_raises(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, path="f.txt", start_line=5, end_line=2
            )
        assert exc.value.parameter_name == "end_line"
