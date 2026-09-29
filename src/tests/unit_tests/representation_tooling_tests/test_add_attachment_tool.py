from unittest.mock import MagicMock

import pytest

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.config.application import StageDisplayLevel
from quickapp.representation_tooling._add_attachment_stage_wrapper import _AddAttachmentStageWrapper
from quickapp.representation_tooling._add_attachment_tool import _AddAttachmentTool
from quickapp.representation_tooling._add_attachment_tool_config import ADD_ATTACHMENT_TOOL_CONFIG


def _build_tool(
    stage_wrapper_builder: MagicMock | None = None,
    stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO,
) -> _AddAttachmentTool:
    return _AddAttachmentTool(
        stage_wrapper_builder=stage_wrapper_builder or MagicMock(),
        tool_config=ADD_ATTACHMENT_TOOL_CONFIG,
        perf_timer=MagicMock(),
        stage_display_level=stage_display_level,
    )


class TestAddAttachmentTool:
    @pytest.mark.asyncio
    async def test_builds_attachment_from_url(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, url="files/bucket/path/report.csv", title="Report", type="text/csv"
        )

        assert len(result.propagate_to_choice) == 1
        attachment = result.propagate_to_choice[0]
        assert attachment.url == "files/bucket/path/report.csv"
        assert attachment.title == "Report.csv"
        assert attachment.type == "text/csv"

    @pytest.mark.asyncio
    async def test_propagates_attachment_to_choice_only(self):
        # The attachment is surfaced via propagate_to_choice (the response), not via
        # result.attachments (which would only render it in the stage).
        tool = _build_tool()
        result = await tool._run_in_stage_async(stage_wrapper=None, url="files/a.pdf")

        assert result.attachments is None
        assert len(result.propagate_to_choice) == 1

    @pytest.mark.asyncio
    async def test_missing_url_raises_invalid_parameter(self):
        tool = _build_tool()
        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await tool._run_in_stage_async(stage_wrapper=None)
        assert excinfo.value.parameter_name == "url"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("explicit_type", [None, ""])
    async def test_unknown_type_raises_invalid_parameter(self, explicit_type: str | None):
        # Guessing text/plain would make the UI offer the file as .txt, so the model is asked
        # to pass the type instead.
        tool = _build_tool()
        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await tool._run_in_stage_async(
                stage_wrapper=None, url="files/bucket/blob", title="Report", type=explicit_type
            )
        assert excinfo.value.parameter_name == "type"
        assert "files/bucket/blob" not in excinfo.value.message

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("url", "expected_type"),
        [
            ("files/bucket/path/report.html", "text/html"),
            ("files/bucket/path/sales_orders_report.md", "text/markdown"),
            ("files/bucket/path/data.csv", "text/csv"),
            ("files/bucket/path/My%20Report.pdf", "application/pdf"),
            ("https://example.com/out/deck.pdf?sig=abc", "application/pdf"),
        ],
    )
    async def test_infers_type_from_url_extension_when_omitted(self, url: str, expected_type: str):
        tool = _build_tool()
        result = await tool._run_in_stage_async(stage_wrapper=None, url=url, title="Report")

        assert result.propagate_to_choice[0].type == expected_type

    @pytest.mark.asyncio
    async def test_infers_type_from_title_when_url_has_no_extension(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, url="files/bucket/blob", title="report.html"
        )

        assert result.propagate_to_choice[0].type == "text/html"

    @pytest.mark.asyncio
    async def test_explicit_type_wins_over_extension(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, url="files/bucket/report.md", type="text/plain"
        )

        assert result.propagate_to_choice[0].type == "text/plain"

    @pytest.mark.asyncio
    async def test_title_defaults_to_url_file_name(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, url="files/bucket/path/My%20Report.html"
        )

        attachment = result.propagate_to_choice[0]
        assert attachment.title == "My Report.html"
        assert attachment.type == "text/html"

    @pytest.mark.asyncio
    async def test_title_without_extension_gets_url_extension(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None,
            url="files/bucket/path/sales_orders_report.md",
            title="Sales Orders (Jan-Jun 2024)",
        )

        attachment = result.propagate_to_choice[0]
        assert attachment.title == "Sales Orders (Jan-Jun 2024).md"
        assert attachment.type == "text/markdown"

    @pytest.mark.asyncio
    async def test_title_with_known_extension_is_kept(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, url="files/bucket/path/report.html", title="summary.htm"
        )

        assert result.propagate_to_choice[0].title == "summary.htm"

    @pytest.mark.asyncio
    async def test_title_without_extension_gets_explicit_type_extension(self):
        tool = _build_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, url="files/bucket/blob", title="Report", type="text/html"
        )

        assert result.propagate_to_choice[0].title == "Report.html"

    @pytest.mark.asyncio
    async def test_content_does_not_echo_the_file(self):
        # The confirmation returned to the LLM is a neutral status that does not contain the
        # file name/path, so there is nothing for the model to parrot back into its reply.
        tool = _build_tool()
        result = await tool._run_in_stage_async(
            stage_wrapper=None, url="files/bucket/report.csv", title="My File"
        )

        assert "report.csv" not in result.content
        assert "My File" not in result.content
        assert result.content
        assert result.content_type == "text/plain"

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

    def test_stage_title_uses_url_file_name(self):
        wrapper = _AddAttachmentStageWrapper(stage=MagicMock())
        title = wrapper._get_stage_title_from_params({"url": "files/bucket/path/sample_test.md"})
        assert title == " `sample_test.md`"

    def test_stage_title_prefers_title_over_url(self):
        wrapper = _AddAttachmentStageWrapper(stage=MagicMock())
        title = wrapper._get_stage_title_from_params(
            {"url": "files/bucket/path/sample_test.md", "title": "My Report"}
        )
        assert title == " `My Report`"

    @pytest.mark.asyncio
    async def test_stage_suppressed_at_info_display_level(self):
        # The tool forces a debug-level stage, so at INFO display no stage is rendered
        # (no stage wrapper is built) while the attachment still propagates to the response.
        builder = MagicMock()
        tool = _build_tool(
            stage_wrapper_builder=builder, stage_display_level=StageDisplayLevel.INFO
        )

        result = await tool.arun(tool_call_id="tc-1", url="files/a.csv")

        builder.build.assert_not_called()
        assert len(result.propagate_to_choice) == 1

    @pytest.mark.asyncio
    async def test_stage_rendered_at_debug_display_level(self):
        # At DEBUG display the stage is built and receives the result.
        stage_wrapper = MagicMock()
        builder = MagicMock()
        builder.build.return_value = stage_wrapper
        tool = _build_tool(
            stage_wrapper_builder=builder, stage_display_level=StageDisplayLevel.DEBUG
        )

        await tool.arun(tool_call_id="tc-1", url="files/a.csv")

        builder.build.assert_called_once()
