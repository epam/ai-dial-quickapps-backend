from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client._exception import DialException

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_files_tooling._read_file_lines_tool import _ReadFileLinesTool
from quickapp.dial_files_tooling._tool_configs import READ_FILE_LINES_TOOL_CONFIG
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_service


def _tool(agent_home_dir: str = "", appdata: str | None = "appbucket"):
    service = make_service(appdata=appdata)
    return _ReadFileLinesTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=READ_FILE_LINES_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=service,
        dial_files_config=make_config(agent_home_dir),
    )


class TestResolveAppdataUrl:
    @pytest.mark.asyncio
    async def test_relative_path_joined_with_home(self):
        tool = _tool()
        url = await tool._resolve_appdata_url("reports/summary.md")
        assert url == "files/appbucket/reports/summary.md"

    @pytest.mark.asyncio
    async def test_subdir_home_prepended(self):
        tool = _tool(agent_home_dir="workspace/")
        url = await tool._resolve_appdata_url("reports/summary.md")
        assert url == "files/appbucket/workspace/reports/summary.md"

    @pytest.mark.asyncio
    async def test_absolute_url_passes_through(self):
        tool = _tool()
        url = await tool._resolve_appdata_url("files/otherbucket/uploads/notes.txt")
        assert url == "files/otherbucket/uploads/notes.txt"

    @pytest.mark.asyncio
    async def test_newline_in_relative_path_rejected(self):
        tool = _tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._resolve_appdata_url("foo\nbar")
        assert exc.value.parameter_name == "path"

    @pytest.mark.asyncio
    async def test_newline_in_absolute_url_rejected(self):
        tool = _tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._resolve_appdata_url("files/x/foo\nbar")
        assert exc.value.parameter_name == "path"

    @pytest.mark.asyncio
    async def test_empty_path_rejected(self):
        tool = _tool()
        with pytest.raises(InvalidToolCallParameterException):
            await tool._resolve_appdata_url("")

    @pytest.mark.asyncio
    async def test_leading_slash_rejected(self):
        tool = _tool()
        with pytest.raises(InvalidToolCallParameterException):
            await tool._resolve_appdata_url("/abs.md")

    @pytest.mark.asyncio
    async def test_dotdot_segment_rejected(self):
        tool = _tool()
        with pytest.raises(InvalidToolCallParameterException):
            await tool._resolve_appdata_url("../escape.md")

    @pytest.mark.asyncio
    async def test_dotdot_substring_rejected(self):
        tool = _tool()
        with pytest.raises(InvalidToolCallParameterException):
            await tool._resolve_appdata_url("a/../b")

    @pytest.mark.asyncio
    async def test_empty_segment_rejected(self):
        tool = _tool()
        with pytest.raises(InvalidToolCallParameterException):
            await tool._resolve_appdata_url("a//b")

    @pytest.mark.asyncio
    async def test_trailing_whitespace_rejected(self):
        tool = _tool()
        with pytest.raises(InvalidToolCallParameterException):
            await tool._resolve_appdata_url("notes.md ")

    @pytest.mark.asyncio
    async def test_no_appdata_raises(self):
        tool = _tool(appdata=None)
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._resolve_appdata_url("notes.md")
        assert "appdata" in exc.value.message

    @pytest.mark.asyncio
    async def test_folder_trailing_slash_preserved(self):
        tool = _tool()
        url = await tool._resolve_appdata_url("reports/")
        assert url == "files/appbucket/reports/"


class TestToDisplayPath:
    @pytest.mark.asyncio
    async def test_home_url_becomes_relative(self):
        tool = _tool()
        await tool._resolve_appdata_url("x.md")
        display = await tool._to_display_path("files/appbucket/reports/summary.md")
        assert display == "reports/summary.md"

    @pytest.mark.asyncio
    async def test_out_of_home_url_unchanged(self):
        tool = _tool()
        await tool._resolve_appdata_url("x.md")
        url = "files/otherbucket/x.md"
        display = await tool._to_display_path(url)
        assert display == url

    @pytest.mark.asyncio
    async def test_home_url_itself_becomes_empty(self):
        tool = _tool()
        await tool._resolve_appdata_url("x.md")
        display = await tool._to_display_path("files/appbucket/")
        assert display == ""


class TestPermissionDeniedWrapper:
    @pytest.mark.asyncio
    async def test_403_from_list_folder_converted_to_invalid_parameter(self):
        from quickapp.dial_files_tooling._list_files_tool import _ListFilesTool
        from quickapp.dial_files_tooling._tool_configs import LIST_FILES_TOOL_CONFIG

        service = make_service()
        service.list_folder = AsyncMock(
            side_effect=DialException(message="forbidden", status_code=403)
        )
        tool = _ListFilesTool(
            stage_wrapper_builder=MagicMock(),
            tool_config=LIST_FILES_TOOL_CONFIG,
            perf_timer=MagicMock(),
            dial_file_service=service,
            dial_files_config=make_config(),
        )
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, path="reports/")
        assert exc.value.parameter_name == "path"
        assert "access denied" in exc.value.message
        assert "reports/" in exc.value.message

    @pytest.mark.asyncio
    async def test_non_403_dial_exception_propagates(self):
        from quickapp.dial_files_tooling._list_files_tool import _ListFilesTool
        from quickapp.dial_files_tooling._tool_configs import LIST_FILES_TOOL_CONFIG

        service = make_service()
        service.list_folder = AsyncMock(
            side_effect=DialException(message="server error", status_code=500)
        )
        tool = _ListFilesTool(
            stage_wrapper_builder=MagicMock(),
            tool_config=LIST_FILES_TOOL_CONFIG,
            perf_timer=MagicMock(),
            dial_file_service=service,
            dial_files_config=make_config(),
        )
        with pytest.raises(DialException):
            await tool._run_in_stage_async(stage_wrapper=None, path="reports/")
