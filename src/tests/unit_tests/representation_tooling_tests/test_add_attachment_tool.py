from unittest.mock import MagicMock

import pytest

from quickapp.representation_tooling._add_attachment_tool import _AddAttachmentTool
from quickapp.representation_tooling._add_attachment_tool_config import ADD_ATTACHMENT_TOOL_CONFIG


def _build_tool() -> _AddAttachmentTool:
    return _AddAttachmentTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=ADD_ATTACHMENT_TOOL_CONFIG,
        perf_timer=MagicMock(),
    )


class TestAddAttachmentTool:
    @pytest.mark.asyncio
    async def test_builds_attachment_from_url(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, url="files/bucket/path/report.csv", title="Report", type="text/csv"
        )

        assert result.attachments is not None
        assert len(result.attachments) == 1
        attachment = result.attachments[0]
        assert attachment.url == "files/bucket/path/report.csv"
        assert attachment.title == "Report"
        assert attachment.type == "text/csv"

    @pytest.mark.asyncio
    async def test_propagates_same_attachment_to_choice(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(stage_wrapper=None, url="files/a.pdf")

        assert result.attachments == result.propagate_to_choice
        assert len(result.propagate_to_choice) == 1

    @pytest.mark.asyncio
    async def test_defaults_type_to_text_plain(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(stage_wrapper=None, url="files/a.bin")

        assert result.attachments is not None
        assert result.attachments[0].type == "text/plain"

    @pytest.mark.asyncio
    async def test_empty_type_falls_back_to_text_plain(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(stage_wrapper=None, url="files/a.bin", type="")

        assert result.attachments is not None
        assert result.attachments[0].type == "text/plain"

    @pytest.mark.asyncio
    async def test_content_uses_title_when_present(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, url="files/a.csv", title="My File"
        )

        assert "My File" in result.content
        assert result.content_type == "text/plain"

    @pytest.mark.asyncio
    async def test_content_falls_back_to_url(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(stage_wrapper=None, url="files/a.csv")

        assert "files/a.csv" in result.content

    @pytest.mark.asyncio
    async def test_stage_wrapper_receives_result(self):
        tool = _build_tool()
        mock_wrapper = MagicMock()
        result = await tool._run_in_stage_async(stage_wrapper=mock_wrapper, url="files/a.csv")

        mock_wrapper.add_result.assert_called_once_with(result)

    def test_config_disables_automatic_propagation(self):
        # propagate_types_to_choice=[] prevents StagedBaseTool from auto-appending the
        # attachment a second time on top of the explicit propagate_to_choice the tool sets.
        assert ADD_ATTACHMENT_TOOL_CONFIG.attachment.propagate_types_to_choice == []
