from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client._exception import EtagMismatchError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.text_file_tooling._tool_configs import WRITE_FILE_TOOL_CONFIG
from quickapp.text_file_tooling._write_file_tool import _WriteFileTool


def _make_mock_dial_client(bucket: str = "mybucket") -> MagicMock:
    mock_bucket_resp = MagicMock()
    mock_bucket_resp.appdata = None
    mock_bucket_resp.bucket = bucket

    mock_dial_client = MagicMock()
    mock_dial_client.bucket = MagicMock()
    mock_dial_client.bucket.get_raw = AsyncMock(return_value=mock_bucket_resp)
    return mock_dial_client


def _make_tool(
    upload_result_url: str = "files/mybucket/generated-files/notes.md",
    bucket: str = "mybucket",
    raise_on_upload: Exception | None = None,
) -> _WriteFileTool:
    mock_service = MagicMock(spec=DialFileService)
    if raise_on_upload:
        mock_service.upload_text = AsyncMock(side_effect=raise_on_upload)
    else:
        mock_service.upload_text = AsyncMock(return_value=upload_result_url)
    mock_dial_client = _make_mock_dial_client(bucket=bucket)
    return _WriteFileTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=WRITE_FILE_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=mock_service,
        dial_client=mock_dial_client,
    )


class TestWriteFile:
    @pytest.mark.asyncio
    async def test_success_returns_url_and_attachment(self):
        url = "files/mybucket/generated-files/notes.md"
        tool = _make_tool(upload_result_url=url)
        result = await tool._run_in_stage_async(
            stage_wrapper=None,
            filename="notes.md",
            content="# Notes",
        )
        assert url in result.content
        assert result.attachments is not None
        assert len(result.attachments) == 1
        assert result.attachments[0].url == url

    @pytest.mark.asyncio
    async def test_uploads_with_if_none_match(self):
        tool = _make_tool()
        await tool._run_in_stage_async(
            stage_wrapper=None,
            filename="notes.md",
            content="hello",
        )
        tool._dial_file_service.upload_text.assert_awaited_once()
        call_kwargs = tool._dial_file_service.upload_text.call_args.kwargs
        assert call_kwargs.get("if_none_match") == "*"

    @pytest.mark.asyncio
    async def test_412_raises_invalid_parameter_filename(self):
        tool = _make_tool(raise_on_upload=EtagMismatchError(message="already exists"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None,
                filename="notes.md",
                content="hello",
            )
        assert exc.value.parameter_name == "filename"
        assert "already exists" in exc.value.message

    @pytest.mark.asyncio
    async def test_empty_filename_raises(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, filename="", content="hello")
        assert exc.value.parameter_name == "filename"

    @pytest.mark.asyncio
    async def test_filename_with_slash_raises(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, filename="dir/file.txt", content="hello"
            )
        assert exc.value.parameter_name == "filename"

    @pytest.mark.asyncio
    async def test_filename_with_dotdot_raises(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, filename="../escape.txt", content="hello"
            )
        assert exc.value.parameter_name == "filename"

    @pytest.mark.asyncio
    async def test_filename_with_leading_whitespace_raises(self):
        tool = _make_tool()
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, filename=" notes.md", content="hello"
            )
        assert exc.value.parameter_name == "filename"
