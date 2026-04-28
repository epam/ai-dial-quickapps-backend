from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client._exception import EtagMismatchError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.text_file_tooling._edit_file_tool import _EditFileTool
from quickapp.text_file_tooling._tool_configs import EDIT_FILE_TOOL_CONFIG

_FILE_URL = "files/bucket/generated-files/notes.md"


def _make_tool(
    file_content: str = "foo bar baz",
    etag: str = "etag1",
    upload_side_effect: Exception | None = None,
) -> _EditFileTool:
    mock_service = MagicMock(spec=DialFileService)
    mock_service.download_file_with_etag = AsyncMock(
        return_value=(file_content.encode("utf-8"), etag)
    )
    if upload_side_effect:
        mock_service.upload_text = AsyncMock(side_effect=upload_side_effect)
    else:
        mock_service.upload_text = AsyncMock(return_value=_FILE_URL)
    mock_service.invalidate_cache = MagicMock()
    return _EditFileTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=EDIT_FILE_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=mock_service,
    )


class TestEditFile:
    @pytest.mark.asyncio
    async def test_success_replaces_unique_substring(self):
        tool = _make_tool("foo bar baz")
        result = await tool._run_in_stage_async(
            stage_wrapper=None,
            file_url=_FILE_URL,
            old_string="bar",
            new_string="qux",
        )
        assert "Edited:" in result.content
        call_args = tool._dial_file_service.upload_text.call_args
        assert call_args.kwargs.get("content") == "foo qux baz"

    @pytest.mark.asyncio
    async def test_success_invalidates_cache(self):
        tool = _make_tool("foo bar baz")
        await tool._run_in_stage_async(
            stage_wrapper=None,
            file_url=_FILE_URL,
            old_string="bar",
            new_string="qux",
        )
        tool._dial_file_service.invalidate_cache.assert_called_once_with(_FILE_URL)

    @pytest.mark.asyncio
    async def test_upload_uses_if_match_etag(self):
        tool = _make_tool("foo bar baz", etag="my-etag")
        await tool._run_in_stage_async(
            stage_wrapper=None,
            file_url=_FILE_URL,
            old_string="bar",
            new_string="qux",
        )
        call_kwargs = tool._dial_file_service.upload_text.call_args.kwargs
        assert call_kwargs.get("if_match") == "my-etag"

    @pytest.mark.asyncio
    async def test_old_string_not_found_raises(self):
        tool = _make_tool("foo bar baz")
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None,
                file_url=_FILE_URL,
                old_string="zzz",
                new_string="qux",
            )
        assert exc.value.parameter_name == "old_string"
        assert "not found" in exc.value.message

    @pytest.mark.asyncio
    async def test_old_string_non_unique_raises(self):
        tool = _make_tool("foo foo foo")
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None,
                file_url=_FILE_URL,
                old_string="foo",
                new_string="bar",
            )
        assert exc.value.parameter_name == "old_string"
        assert "3 times" in exc.value.message

    @pytest.mark.asyncio
    async def test_same_old_and_new_string_raises(self):
        tool = _make_tool("foo bar baz")
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None,
                file_url=_FILE_URL,
                old_string="bar",
                new_string="bar",
            )
        assert exc.value.parameter_name == "new_string"

    @pytest.mark.asyncio
    async def test_concurrent_modification_raises(self):
        tool = _make_tool(
            "foo bar baz",
            upload_side_effect=EtagMismatchError(message="412"),
        )
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None,
                file_url=_FILE_URL,
                old_string="bar",
                new_string="qux",
            )
        assert exc.value.parameter_name == "file_url"
        assert "concurrently" in exc.value.message

    @pytest.mark.asyncio
    async def test_cache_not_invalidated_on_failure(self):
        tool = _make_tool("foo bar baz", upload_side_effect=EtagMismatchError(message="412"))
        with pytest.raises(InvalidToolCallParameterException):
            await tool._run_in_stage_async(
                stage_wrapper=None,
                file_url=_FILE_URL,
                old_string="bar",
                new_string="qux",
            )
        tool._dial_file_service.invalidate_cache.assert_not_called()
