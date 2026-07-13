import pytest
from aidial_client._exception import ResourceNotFoundError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_files_tooling._read_file_lines_tool import _ReadFileLinesTool
from quickapp.dial_files_tooling._tool_configs import READ_FILE_LINES_TOOL_CONFIG
from tests.unit_tests.dial_files_tooling._helpers import make_service, make_tool


def _make_tool(content: bytes = b"a\nb\nc\nd\ne") -> _ReadFileLinesTool:
    service = make_service()
    service.download_file.return_value = (content, None)
    return make_tool(_ReadFileLinesTool, READ_FILE_LINES_TOOL_CONFIG, service=service)


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

    @pytest.mark.asyncio
    async def test_missing_file_raises_friendly_not_found(self):
        tool = _make_tool()
        tool._dial_file_service.download_file.side_effect = ResourceNotFoundError(message="404")
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, path="missing.txt", start_line=0, end_line=2
            )
        assert exc.value.parameter_name == "path"
        assert "file not found" in exc.value.message
