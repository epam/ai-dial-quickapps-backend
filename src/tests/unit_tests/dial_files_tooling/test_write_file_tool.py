from unittest.mock import MagicMock

import pytest
from aidial_client._exception import EtagMismatchError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_files_tooling._tool_configs import WRITE_FILE_TOOL_CONFIG
from quickapp.dial_files_tooling._write_file_tool import _WriteFileTool
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_service


def _make_tool(
    upload_url: str = "files/appbucket/reports/x.md",
    raise_on_write: Exception | None = None,
) -> _WriteFileTool:
    service = make_service()
    if raise_on_write:
        service.write_file.side_effect = raise_on_write
    else:
        service.write_file.return_value = upload_url
    return _WriteFileTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=WRITE_FILE_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=service,
        dial_files_config=make_config(),
    )


class TestWriteFile:
    @pytest.mark.asyncio
    async def test_nested_path_success(self):
        tool = _make_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="reports/2026-Q1/summary.md", content="hi"
        )
        tool._dial_file_service.write_file.assert_awaited_once_with(
            url="files/appbucket/reports/2026-Q1/summary.md",
            content="hi",
            content_type="text/plain",
            overwrite=False,
        )
        assert "reports/2026-Q1/summary.md" in result.content

    @pytest.mark.asyncio
    async def test_absolute_url_rejected(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, path="files/x/a.md", content="hi")
        assert exc.value.parameter_name == "path"
        assert "relative" in exc.value.message

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException):
            await tool._run_in_stage_async(stage_wrapper=None, path="../escape.md", content="x")

    @pytest.mark.asyncio
    async def test_leading_slash_rejected(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException):
            await tool._run_in_stage_async(stage_wrapper=None, path="/abs.md", content="x")

    @pytest.mark.asyncio
    async def test_empty_segment_rejected(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException):
            await tool._run_in_stage_async(stage_wrapper=None, path="a//b", content="x")

    @pytest.mark.asyncio
    async def test_content_type_propagated(self):
        tool = _make_tool()
        await tool._run_in_stage_async(
            stage_wrapper=None, path="data.csv", content="a,b", content_type="text/csv"
        )
        call_kwargs = tool._dial_file_service.write_file.call_args.kwargs
        assert call_kwargs["content_type"] == "text/csv"

    @pytest.mark.asyncio
    async def test_overwrite_false_collision_asks_user(self):
        tool = _make_tool(raise_on_write=EtagMismatchError(message="exists"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, path="reports/x.md", content="x")
        assert exc.value.parameter_name == "path"
        # Guides the model to seek user approval before retrying with overwrite=True.
        assert "Ask the user" in exc.value.message
        assert "overwrite=True" in exc.value.message

    @pytest.mark.asyncio
    async def test_overwrite_true_forwarded_to_service(self):
        tool = _make_tool()
        await tool._run_in_stage_async(stage_wrapper=None, path="r.md", content="x", overwrite=True)
        assert tool._dial_file_service.write_file.call_args.kwargs["overwrite"] is True

    @pytest.mark.asyncio
    async def test_appdata_missing_raises(self):
        service = make_service(appdata=None)
        tool = _WriteFileTool(
            stage_wrapper_builder=MagicMock(),
            tool_config=WRITE_FILE_TOOL_CONFIG,
            perf_timer=MagicMock(),
            dial_file_service=service,
            dial_files_config=make_config(),
        )
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, path="x.md", content="x")
        assert "appdata" in exc.value.message

    @pytest.mark.asyncio
    async def test_success_message_uses_relative_path(self):
        tool = _make_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="reports/x.md", content="hi"
        )
        assert result.content == "File written: reports/x.md"
        assert result.attachments is not None
        assert result.attachments[0].title == "reports/x.md"
