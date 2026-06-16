import pytest
from aidial_client._exception import ResourceNotFoundError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_files_tooling._delete_file_tool import _DeleteFileTool
from quickapp.dial_files_tooling._tool_configs import DELETE_FILE_TOOL_CONFIG
from tests.unit_tests.dial_files_tooling._helpers import make_service, make_tool


def _make_tool(delete_side_effect: Exception | None = None) -> _DeleteFileTool:
    service = make_service()
    if delete_side_effect:
        service.delete.side_effect = delete_side_effect
    return make_tool(_DeleteFileTool, DELETE_FILE_TOOL_CONFIG, service=service)


class TestDeleteFile:
    @pytest.mark.asyncio
    async def test_relative_path_success(self):
        tool = _make_tool()
        result = await tool._run_in_stage_async(stage_wrapper=None, path="reports/old.md")
        assert result.content == "Deleted: reports/old.md"
        tool._dial_file_service.delete.assert_awaited_once_with("files/appbucket/reports/old.md")

    @pytest.mark.asyncio
    async def test_absolute_url_rejected(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, path="files/o/x.md")
        assert exc.value.parameter_name == "path"

    @pytest.mark.asyncio
    async def test_not_found_raises(self):
        tool = _make_tool(delete_side_effect=ResourceNotFoundError(message="404"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, path="reports/old.md")
        assert exc.value.parameter_name == "path"
        assert "not found" in exc.value.message
