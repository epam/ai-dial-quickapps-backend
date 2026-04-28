from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client._exception import ResourceNotFoundError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.text_file_tooling._delete_file_tool import _DeleteFileTool
from quickapp.text_file_tooling._tool_configs import DELETE_FILE_TOOL_CONFIG

_VALID_URL = "files/bucket/generated-files/notes.md"
_USER_URL = "files/bucket/user-uploads/data.csv"


def _make_tool(delete_side_effect: Exception | None = None) -> _DeleteFileTool:
    mock_dial_client = MagicMock()
    if delete_side_effect:
        mock_dial_client.files.delete = AsyncMock(side_effect=delete_side_effect)
    else:
        mock_dial_client.files.delete = AsyncMock(return_value=None)
    return _DeleteFileTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=DELETE_FILE_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=MagicMock(spec=DialFileService),
        dial_client=mock_dial_client,
    )


class TestDeleteFile:
    @pytest.mark.asyncio
    async def test_success_returns_confirmation(self):
        tool = _make_tool()
        result = await tool._run_in_stage_async(stage_wrapper=None, file_url=_VALID_URL)
        assert "Deleted:" in result.content
        assert _VALID_URL in result.content

    @pytest.mark.asyncio
    async def test_calls_dial_delete(self):
        tool = _make_tool()
        await tool._run_in_stage_async(stage_wrapper=None, file_url=_VALID_URL)
        tool._DeleteFileTool__dial_client.files.delete.assert_awaited_once_with(_VALID_URL)

    @pytest.mark.asyncio
    async def test_url_outside_generated_files_raises(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, file_url=_USER_URL)
        assert exc.value.parameter_name == "file_url"
        assert "generated-files" in exc.value.message

    @pytest.mark.asyncio
    async def test_404_raises_invalid_parameter(self):
        tool = _make_tool(delete_side_effect=ResourceNotFoundError(message="not found"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, file_url=_VALID_URL)
        assert exc.value.parameter_name == "file_url"
        assert "not found" in exc.value.message
