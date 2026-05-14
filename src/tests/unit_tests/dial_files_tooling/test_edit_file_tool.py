from unittest.mock import MagicMock

import pytest
from aidial_client._exception import EtagMismatchError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_files_tooling._edit_file_tool import _EditFileTool
from quickapp.dial_files_tooling._tool_configs import EDIT_FILE_TOOL_CONFIG
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_service


def _make_tool(
    content: str = "foo bar baz",
    etag: str = "etag1",
    upload_side_effect: Exception | None = None,
) -> _EditFileTool:
    service = make_service()
    service.download_file.return_value = (content.encode("utf-8"), MagicMock(etag=etag))
    if upload_side_effect:
        service.write_file.side_effect = upload_side_effect
    else:
        service.write_file.return_value = "files/appbucket/r.md"
    return _EditFileTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=EDIT_FILE_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=service,
        dial_files_config=make_config(),
    )


class TestEditFile:
    @pytest.mark.asyncio
    async def test_relative_path_resolves(self):
        tool = _make_tool()
        await tool._run_in_stage_async(
            stage_wrapper=None, path="r.md", old_string="bar", new_string="qux"
        )
        tool._dial_file_service.download_file.assert_awaited_once_with("files/appbucket/r.md")

    @pytest.mark.asyncio
    async def test_absolute_url_rejected(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None,
                path="files/o/r.md",
                old_string="bar",
                new_string="qux",
            )
        assert exc.value.parameter_name == "path"

    @pytest.mark.asyncio
    async def test_old_string_not_found_raises(self):
        tool = _make_tool("foo bar baz")
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, path="r.md", old_string="zzz", new_string="x"
            )
        assert exc.value.parameter_name == "old_string"

    @pytest.mark.asyncio
    async def test_non_unique_raises(self):
        tool = _make_tool("foo foo foo")
        with pytest.raises(InvalidToolCallParameterException):
            await tool._run_in_stage_async(
                stage_wrapper=None, path="r.md", old_string="foo", new_string="x"
            )

    @pytest.mark.asyncio
    async def test_concurrent_modification_raises(self):
        tool = _make_tool(upload_side_effect=EtagMismatchError(message="412"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, path="r.md", old_string="bar", new_string="qux"
            )
        assert exc.value.parameter_name == "path"
        assert "concurrently" in exc.value.message

    @pytest.mark.asyncio
    async def test_success_message_uses_relative_path(self):
        tool = _make_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="r.md", old_string="bar", new_string="qux"
        )
        assert result.content == "Edited: r.md"
