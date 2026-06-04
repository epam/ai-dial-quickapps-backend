from unittest.mock import MagicMock

import pytest
from aidial_client._exception import DialException, EtagMismatchError, ResourceNotFoundError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_files_tooling._copy_file_tool import _CopyFileTool
from quickapp.dial_files_tooling._tool_configs import COPY_FILE_TOOL_CONFIG
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_service


def _make_tool(side_effect: Exception | None = None) -> _CopyFileTool:
    service = make_service()
    if side_effect:
        service.copy.side_effect = side_effect
    return _CopyFileTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=COPY_FILE_TOOL_CONFIG,
        perf_timer=MagicMock(),
        dial_file_service=service,
        dial_files_config=make_config(),
    )


class TestCopyFile:
    @pytest.mark.asyncio
    async def test_relative_source_happy(self):
        tool = _make_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, source="drafts/a.md", destination="final/a.md"
        )
        tool._dial_file_service.copy.assert_awaited_once_with(
            source_url="files/appbucket/drafts/a.md",
            destination_url="files/appbucket/final/a.md",
            overwrite=False,
        )
        assert result.content == "Copied to: final/a.md"
        tool._dial_file_service.invalidate_cache.assert_not_called()

    @pytest.mark.asyncio
    async def test_absolute_source_happy(self):
        tool = _make_tool()
        await tool._run_in_stage_async(
            stage_wrapper=None,
            source="files/other/uploads/data.csv",
            destination="inputs/data.csv",
        )
        call_kwargs = tool._dial_file_service.copy.call_args.kwargs
        assert call_kwargs["source_url"] == "files/other/uploads/data.csv"

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
        assert "overwrite=True" in exc.value.message

    @pytest.mark.asyncio
    async def test_overwrite_true_forwarded(self):
        tool = _make_tool()
        await tool._run_in_stage_async(
            stage_wrapper=None, source="a.md", destination="b.md", overwrite=True
        )
        assert tool._dial_file_service.copy.call_args.kwargs["overwrite"] is True

    @pytest.mark.asyncio
    async def test_source_not_found_raises(self):
        tool = _make_tool(side_effect=ResourceNotFoundError(message="404"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, source="missing.md", destination="b.md"
            )
        assert exc.value.parameter_name == "source"

    @pytest.mark.asyncio
    async def test_403_raises(self):
        tool = _make_tool(side_effect=DialException(message="forbidden", status_code=403))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, source="a.md", destination="b.md")
        assert exc.value.parameter_name == "source"
        # The message shows the user-facing source, not the resolved internal appdata URL.
        assert "access denied: a.md" in exc.value.message
        assert "appbucket" not in exc.value.message
