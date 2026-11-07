"""A partial project move reaches the model as a tool error, without the retry framing."""

from unittest.mock import MagicMock

import pytest

from quickapp.dial_core_services.exceptions import PartialMoveException
from quickapp.dial_files_tooling._dial_files_tool_error_exception import DialFilesToolErrorException
from quickapp.dial_files_tooling._move_file_tool import _MoveFileTool
from quickapp.dial_files_tooling._tool_configs import MOVE_FILE_TOOL_CONFIG
from tests.unit_tests.dial_files_tooling._helpers import make_service, make_tool

_PARTIAL_MOVE = PartialMoveException(
    "projects/b/p/files/artifacts/a.md", "projects/b/p/files/artifacts/b.md"
)


def _make_tool(tool_cls, tool_config, failing_method: str, error: Exception):
    service = make_service()
    service.download_file.return_value = (b"foo", MagicMock(etag="etag"))
    getattr(service, failing_method).side_effect = error
    return make_tool(tool_cls, tool_config, service=service)


@pytest.mark.asyncio
async def test_a_partial_move_is_a_tool_error():
    tool = _make_tool(_MoveFileTool, MOVE_FILE_TOOL_CONFIG, "move", _PARTIAL_MOVE)

    with pytest.raises(DialFilesToolErrorException) as excinfo:
        await tool._run_in_stage_async(stage_wrapper=None, source="a.md", destination="b.md")

    assert excinfo.value.error_message == str(_PARTIAL_MOVE)


@pytest.mark.asyncio
async def test_the_model_gets_the_message_without_the_retry_framing():
    tool = _make_tool(_MoveFileTool, MOVE_FILE_TOOL_CONFIG, "move", _PARTIAL_MOVE)

    result = await tool.arun("call-1", source="a.md", destination="b.md")

    assert str(_PARTIAL_MOVE) in result.content
    assert "try to call the tool again" not in result.content
