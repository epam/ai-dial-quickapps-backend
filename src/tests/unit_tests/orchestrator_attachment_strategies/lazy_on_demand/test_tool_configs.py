from quickapp.orchestrator_attachment_strategies.lazy_on_demand._tool_configs import (
    GET_CONTENT_TOOL_CONFIG,
    render_get_content_tool_config,
)


def _function_description(tool):
    return tool.open_ai_tool.function.description


def _attachment_url_description(tool):
    return tool.open_ai_tool.function.parameters.properties["attachment_url"].description


class TestRenderGetContentToolConfig:
    def test_describes_cross_turn_reload_behavior(self):
        description = _function_description(GET_CONTENT_TOOL_CONFIG)
        assert "not kept across user turns" in description
        assert "call this tool again" in description

    def test_attachment_url_parameter_describes_file_url_form(self):
        param_description = _attachment_url_description(GET_CONTENT_TOOL_CONFIG)
        assert "file:url::" in (param_description or "")

    def test_appends_accepted_mime_types_to_function_description(self):
        rendered = render_get_content_tool_config(["application/pdf", "text/csv"])
        description = _function_description(rendered)
        assert description.endswith("Accepted MIME types: application/pdf, text/csv.")

    def test_appends_accepted_mime_types_to_attachment_url_parameter_description(self):
        rendered = render_get_content_tool_config(["application/pdf", "text/csv"])
        param_description = _attachment_url_description(rendered)
        assert param_description.endswith("Accepted MIME types: application/pdf, text/csv.")

    def test_preserves_wildcard_patterns_verbatim(self):
        rendered = render_get_content_tool_config(["image/*", "application/pdf"])
        assert "image/*" in _function_description(rendered)
        assert "image/*" in _attachment_url_description(rendered)

    def test_does_not_mutate_template_constant(self):
        original_function_description = GET_CONTENT_TOOL_CONFIG.open_ai_tool.function.description
        original_param_description = (
            GET_CONTENT_TOOL_CONFIG.open_ai_tool.function.parameters.properties[
                "attachment_url"
            ].description
        )

        render_get_content_tool_config(["application/pdf"])
        render_get_content_tool_config(["text/csv", "image/*"])

        assert (
            GET_CONTENT_TOOL_CONFIG.open_ai_tool.function.description
            == original_function_description
        )
        assert (
            GET_CONTENT_TOOL_CONFIG.open_ai_tool.function.parameters.properties[
                "attachment_url"
            ].description
            == original_param_description
        )
        # No "Accepted MIME types" sentence ever leaks into the template.
        assert "Accepted MIME types" not in original_function_description
        assert "Accepted MIME types" not in (original_param_description or "")

    def test_empty_list_skips_append(self):
        rendered = render_get_content_tool_config([])
        assert "Accepted MIME types" not in _function_description(rendered)
        assert "Accepted MIME types" not in (_attachment_url_description(rendered) or "")
