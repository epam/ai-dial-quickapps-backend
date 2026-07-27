"""The tool-error exceptions keep their string form structural (content rule, #436)
while preserving the body on ``error_message`` for the LLM/user channels (#408)."""

from quickapp.common.exceptions.tool_error import ToolErrorException
from quickapp.common.tool_fallback.utils import extract_error_content
from quickapp.mcp_tooling._mcp_tool_error_exception import MCPToolErrorException
from quickapp.rest_api_tooling._rest_api_tool_error_exception import RestApiToolErrorException

_BODY = "detailed tool response body that must never leak into logs"


class TestStructuralMessage:
    def test_base_str_omits_body(self):
        e = ToolErrorException("my_tool", _BODY)
        assert _BODY not in str(e)
        assert f"content_length={len(_BODY)}" in str(e)

    def test_mcp_str_omits_body_but_names_tool(self):
        e = MCPToolErrorException("mcp_tool", _BODY)
        rendered = str(e)
        assert _BODY not in rendered
        assert "mcp_tool" in rendered
        assert f"content_length={len(_BODY)}" in rendered


class TestBodyPreservedForNonLogChannels:
    def test_base_keeps_error_message_and_tool_name(self):
        e = ToolErrorException("my_tool", _BODY)
        assert e.error_message == _BODY
        assert e.tool_name == "my_tool"

    def test_mcp_keeps_error_message(self):
        assert MCPToolErrorException("mcp_tool", _BODY).error_message == _BODY

    def test_forwarding_to_llm_still_carries_body(self):
        e = MCPToolErrorException("mcp_tool", _BODY)
        assert _BODY in extract_error_content(e)

    def test_rest_error_message_is_status_only(self):
        # REST's error_message is already a status string (no body); left as-is.
        e = RestApiToolErrorException("rest_tool", "HTTP error 500 while calling REST API tool.")
        assert e.error_message == "HTTP error 500 while calling REST API tool."


class TestUserFacingMessage:
    def test_base_carries_body_and_tool_name(self):
        e = ToolErrorException("my_tool", _BODY)
        assert e.user_facing_message == f"Tool 'my_tool' returned an error: {_BODY}"

    def test_mcp_uses_tool_kind_label(self):
        e = MCPToolErrorException("mcp_tool", _BODY)
        assert e.user_facing_message == f"MCP tool 'mcp_tool' returned an error: {_BODY}"
