from unittest.mock import MagicMock

import pytest
from aidial_client._exception import ResourceNotFoundError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_core_services.dial_file_service import FolderEntry
from quickapp.dial_files_tooling._list_files_tool import _ListFilesTool
from quickapp.dial_files_tooling._tool_configs import LIST_FILES_TOOL_CONFIG
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_service


def _make_tool(entries: list[FolderEntry] | None = None, side_effect: Exception | None = None):
    service = make_service()
    if side_effect:
        service.list_folder.side_effect = side_effect
    else:
        service.list_folder.return_value = entries or []
    return _ListFilesTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=LIST_FILES_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=service,
        dial_files_config=make_config(),
    )


class TestListFiles:
    @pytest.mark.asyncio
    async def test_relative_folder_resolves_with_trailing_slash(self):
        tool = _make_tool()
        await tool._run_in_stage_async(stage_wrapper=None, path="reports/")
        tool._dial_file_service.list_folder.assert_awaited_once_with(
            "files/appbucket/reports/", max_depth=1
        )

    @pytest.mark.asyncio
    async def test_path_auto_gets_trailing_slash(self):
        tool = _make_tool()
        await tool._run_in_stage_async(stage_wrapper=None, path="reports")
        call = tool._dial_file_service.list_folder.call_args
        assert call.args[0].endswith("/")

    @pytest.mark.asyncio
    async def test_max_depth_out_of_range_raises(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, path="reports/", max_depth=11)
        assert exc.value.parameter_name == "max_depth"

    @pytest.mark.asyncio
    async def test_max_depth_zero_raises(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException):
            await tool._run_in_stage_async(stage_wrapper=None, path="reports/", max_depth=0)

    @pytest.mark.asyncio
    async def test_folder_not_found_raises(self):
        tool = _make_tool(side_effect=ResourceNotFoundError(message="404"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, path="missing/")
        assert exc.value.parameter_name == "path"
        assert "folder not found" in exc.value.message

    @pytest.mark.asyncio
    async def test_not_a_folder_raises(self):
        tool = _make_tool(side_effect=ValueError("not a folder"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, path="x/")
        assert "not a folder" in exc.value.message

    @pytest.mark.asyncio
    async def test_listing_under_home_uses_relative_paths(self):
        entries = [
            FolderEntry(
                url="files/appbucket/reports/summary.md",
                name="summary.md",
                is_folder=False,
                size=1234,
            ),
            FolderEntry(
                url="files/appbucket/reports/images/",
                name="images",
                is_folder=True,
                size=None,
            ),
        ]
        tool = _make_tool(entries=entries)
        result = await tool._run_in_stage_async(stage_wrapper=None, path="reports/")
        assert "reports/summary.md" in result.content
        assert "1.2 KB" in result.content
        assert "reports/images/" in result.content

    @pytest.mark.asyncio
    async def test_listing_outside_home_uses_absolute_paths(self):
        entries = [
            FolderEntry(
                url="files/other/uploads/notes.txt",
                name="notes.txt",
                is_folder=False,
                size=42,
            ),
        ]
        tool = _make_tool(entries=entries)
        result = await tool._run_in_stage_async(stage_wrapper=None, path="files/other/uploads/")
        assert "files/other/uploads/notes.txt" in result.content
        assert "42 B" in result.content

    @pytest.mark.asyncio
    async def test_empty_folder(self):
        tool = _make_tool(entries=[])
        result = await tool._run_in_stage_async(stage_wrapper=None, path="reports/")
        assert result.content == "(empty folder)"
