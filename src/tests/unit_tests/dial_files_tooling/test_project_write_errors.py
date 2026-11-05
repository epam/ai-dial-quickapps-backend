"""Project write failures reach the model as tool errors, without the retry framing."""

from unittest.mock import MagicMock

import pytest

from quickapp.dial_core_services.exceptions import (
    PartialMoveException,
    ProjectWriteConflictException,
)
from quickapp.dial_files_tooling._copy_file_tool import _CopyFileTool
from quickapp.dial_files_tooling._dial_files_tool_error_exception import DialFilesToolErrorException
from quickapp.dial_files_tooling._edit_file_tool import _EditFileTool
from quickapp.dial_files_tooling._move_file_tool import _MoveFileTool
from quickapp.dial_files_tooling._tool_configs import (
    COPY_FILE_TOOL_CONFIG,
    EDIT_FILE_TOOL_CONFIG,
    MOVE_FILE_TOOL_CONFIG,
    WRITE_FILE_TOOL_CONFIG,
)
from quickapp.dial_files_tooling._write_file_tool import _WriteFileTool
from tests.unit_tests.dial_files_tooling._helpers import make_service, make_tool

_CONFLICT = ProjectWriteConflictException("projects/b/p/files/artifacts/a.md", 5)
_PARTIAL_MOVE = PartialMoveException(
    "projects/b/p/files/artifacts/a.md", "projects/b/p/files/artifacts/b.md"
)

_CASES = [
    (_WriteFileTool, WRITE_FILE_TOOL_CONFIG, "write_file", {"path": "a.md", "content": "x"}),
    (
        _EditFileTool,
        EDIT_FILE_TOOL_CONFIG,
        "write_file",
        {"path": "a.md", "old_string": "foo", "new_string": "bar"},
    ),
    (_CopyFileTool, COPY_FILE_TOOL_CONFIG, "copy", {"source": "a.md", "destination": "b.md"}),
    (_MoveFileTool, MOVE_FILE_TOOL_CONFIG, "move", {"source": "a.md", "destination": "b.md"}),
]


def _make_tool(tool_cls, tool_config, failing_method: str, error: Exception):
    service = make_service()
    service.download_file.return_value = (b"foo", MagicMock(etag="etag"))
    getattr(service, failing_method).side_effect = error
    return make_tool(tool_cls, tool_config, service=service)


@pytest.mark.parametrize("tool_cls, tool_config, failing_method, kwargs", _CASES)
@pytest.mark.asyncio
async def test_a_project_write_conflict_is_a_tool_error(
    tool_cls, tool_config, failing_method, kwargs
):
    tool = _make_tool(tool_cls, tool_config, failing_method, _CONFLICT)

    with pytest.raises(DialFilesToolErrorException) as excinfo:
        await tool._run_in_stage_async(stage_wrapper=None, **kwargs)

    assert excinfo.value.error_message == str(_CONFLICT)


@pytest.mark.asyncio
async def test_a_partial_move_is_a_tool_error():
    tool = _make_tool(_MoveFileTool, MOVE_FILE_TOOL_CONFIG, "move", _PARTIAL_MOVE)

    with pytest.raises(DialFilesToolErrorException) as excinfo:
        await tool._run_in_stage_async(stage_wrapper=None, source="a.md", destination="b.md")

    assert excinfo.value.error_message == str(_PARTIAL_MOVE)


@pytest.mark.parametrize("tool_cls, tool_config, failing_method, kwargs", _CASES)
@pytest.mark.asyncio
async def test_the_model_gets_the_message_without_the_retry_framing(
    tool_cls, tool_config, failing_method, kwargs
):
    tool = _make_tool(tool_cls, tool_config, failing_method, _CONFLICT)

    result = await tool.arun("call-1", **kwargs)

    assert str(_CONFLICT) in result.content
    assert "try to call the tool again" not in result.content
