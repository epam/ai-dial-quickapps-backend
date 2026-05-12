from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client._exception import EtagMismatchError, ResourceNotFoundError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_files_tooling._tool_configs import WRITE_FILE_TOOL_CONFIG
from quickapp.dial_files_tooling._write_file_tool import _WriteFileTool
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_dial_client, make_service


def _make_tool(
    upload_url: str = "files/appbucket/reports/x.md",
    raise_on_upload: Exception | None = None,
    get_metadata_side_effect: Exception | None = None,
    get_metadata_etag: str | None = "etag1",
) -> _WriteFileTool:
    service = make_service()
    if raise_on_upload:
        service.upload_text.side_effect = raise_on_upload
    else:
        service.upload_text.return_value = upload_url
    client = make_dial_client()
    if get_metadata_side_effect:
        client.files.get_metadata.side_effect = get_metadata_side_effect
    else:
        client.files.get_metadata.return_value = MagicMock(etag=get_metadata_etag)
    return _WriteFileTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=WRITE_FILE_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=service,
        dial_client=client,
        dial_files_config=make_config(),
    )


class TestWriteFile:
    @pytest.mark.asyncio
    async def test_nested_path_success(self):
        tool = _make_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="reports/2026-Q1/summary.md", content="hi"
        )
        tool._dial_file_service.upload_text.assert_awaited_once_with(
            url="files/appbucket/reports/2026-Q1/summary.md",
            content="hi",
            content_type="text/plain",
            if_none_match="*",
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
        call_kwargs = tool._dial_file_service.upload_text.call_args.kwargs
        assert call_kwargs["content_type"] == "text/csv"

    @pytest.mark.asyncio
    async def test_content_type_with_newline_rejected(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, path="x.md", content="x", content_type="text/plain\nfoo"
            )
        assert exc.value.parameter_name == "content_type"

    @pytest.mark.asyncio
    async def test_overwrite_false_collision_raises(self):
        tool = _make_tool(raise_on_upload=EtagMismatchError(message="exists"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, path="reports/x.md", content="x")
        assert exc.value.parameter_name == "path"
        assert "overwrite=True" in exc.value.message

    @pytest.mark.asyncio
    async def test_overwrite_true_uses_etag(self):
        tool = _make_tool(get_metadata_etag="etag-99")
        await tool._run_in_stage_async(
            stage_wrapper=None, path="reports/x.md", content="new", overwrite=True
        )
        call_kwargs = tool._dial_file_service.upload_text.call_args.kwargs
        assert call_kwargs["if_match"] == "etag-99"
        tool._dial_file_service.invalidate_cache.assert_called_once_with(
            "files/appbucket/reports/x.md"
        )

    @pytest.mark.asyncio
    async def test_overwrite_true_falls_through_when_not_found(self):
        tool = _make_tool(get_metadata_side_effect=ResourceNotFoundError(message="404"))
        await tool._run_in_stage_async(
            stage_wrapper=None, path="reports/x.md", content="new", overwrite=True
        )
        call_kwargs = tool._dial_file_service.upload_text.call_args.kwargs
        assert call_kwargs.get("if_none_match") == "*"

    @pytest.mark.asyncio
    async def test_overwrite_true_concurrent_modification_raises(self):
        service = make_service()
        service.upload_text = AsyncMock(side_effect=EtagMismatchError(message="412"))
        client = make_dial_client()
        client.files.get_metadata.return_value = MagicMock(etag="etag1")
        tool = _WriteFileTool(
            stage_wrapper_builder=MagicMock(),
            tool_config=WRITE_FILE_TOOL_CONFIG,
            perf_timer=MagicMock(),
            dial_file_service=service,
            dial_client=client,
            dial_files_config=make_config(),
        )
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, path="r.md", content="x", overwrite=True
            )
        assert "concurrently" in exc.value.message

    @pytest.mark.asyncio
    async def test_appdata_missing_raises(self):
        service = make_service()
        client = make_dial_client(appdata=None)
        tool = _WriteFileTool(
            stage_wrapper_builder=MagicMock(),
            tool_config=WRITE_FILE_TOOL_CONFIG,
            perf_timer=MagicMock(),
            dial_file_service=service,
            dial_client=client,
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
