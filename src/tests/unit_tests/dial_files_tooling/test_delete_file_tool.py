from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client._exception import ResourceNotFoundError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_files_tooling._delete_file_tool import _DeleteFileTool
from quickapp.dial_files_tooling._tool_configs import DELETE_FILE_TOOL_CONFIG
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_dial_client, make_service


def _make_tool(delete_side_effect: Exception | None = None) -> _DeleteFileTool:
    client = make_dial_client()
    if delete_side_effect:
        client.files.delete = AsyncMock(side_effect=delete_side_effect)
    return _DeleteFileTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=DELETE_FILE_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=make_service(),
        dial_client=client,
        dial_files_config=make_config(),
    )


class TestDeleteFile:
    @pytest.mark.asyncio
    async def test_relative_path_success(self):
        tool = _make_tool()
        result = await tool._run_in_stage_async(stage_wrapper=None, path="reports/old.md")
        assert result.content == "Deleted: reports/old.md"
        tool._dial_client.files.delete.assert_awaited_once_with("files/appbucket/reports/old.md")

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
