from unittest.mock import MagicMock

import pytest
from aidial_client._exception import EtagMismatchError, ResourceNotFoundError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_files_tooling._move_file_tool import _MoveFileTool
from quickapp.dial_files_tooling._tool_configs import MOVE_FILE_TOOL_CONFIG
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_service


def _make_tool(side_effect: Exception | None = None) -> _MoveFileTool:
    service = make_service()
    if side_effect:
        service.move.side_effect = side_effect
    return _MoveFileTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=MOVE_FILE_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=service,
        dial_files_config=make_config(),
    )


class TestMoveFile:
    @pytest.mark.asyncio
    async def test_relative_to_relative_happy(self):
        tool = _make_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, source="drafts/r-v1.md", destination="final/r.md"
        )
        tool._dial_file_service.move.assert_awaited_once_with(
            source_url="files/appbucket/drafts/r-v1.md",
            destination_url="files/appbucket/final/r.md",
            overwrite=False,
        )
        assert result.content == "Moved to: final/r.md"

    @pytest.mark.asyncio
    async def test_absolute_source_rejected(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, source="files/o/a.md", destination="b.md"
            )
        assert exc.value.parameter_name == "source"

    @pytest.mark.asyncio
    async def test_absolute_destination_rejected(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, source="a.md", destination="files/o/b.md"
            )
        assert exc.value.parameter_name == "destination"

    @pytest.mark.asyncio
    async def test_collision_overwrite_false_raises(self):
        tool = _make_tool(side_effect=EtagMismatchError(message="412"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, source="a.md", destination="b.md")
        assert exc.value.parameter_name == "destination"

    @pytest.mark.asyncio
    async def test_source_not_found_raises(self):
        tool = _make_tool(side_effect=ResourceNotFoundError(message="404"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, source="missing.md", destination="b.md"
            )
        assert exc.value.parameter_name == "source"
