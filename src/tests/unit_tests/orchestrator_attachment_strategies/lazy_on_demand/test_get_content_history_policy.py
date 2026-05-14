from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_history_policy import (
    _GetContentHistoryPolicy,
)


class TestGetContentHistoryPolicy:
    def test_strips_attachments_but_keeps_other_custom_content_fields(self):
        policy = _GetContentHistoryPolicy()
        history: list[dict[str, object]] = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "tc-1",
                        "type": "function",
                        "function": {
                            "name": INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
                            "arguments": "{}",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "tc-1",
                "content": '{"ok": true}',
                "custom_content": {
                    "attachments": [{"url": "files/bucket/a.pdf", "type": "application/pdf"}],
                    "state": {"k": "v"},
                },
            },
        ]

        result = policy.apply(history)
        tool_msg = result[1]
        assert "custom_content" in tool_msg
        custom_content = tool_msg["custom_content"]
        assert isinstance(custom_content, dict)
        assert "attachments" not in custom_content
        assert custom_content.get("state") == {"k": "v"}

    def test_does_not_affect_other_tool_names(self):
        policy = _GetContentHistoryPolicy()
        history: list[dict[str, object]] = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "tc-1",
                        "type": "function",
                        "function": {"name": "some_other_tool", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "tc-1",
                "content": "out",
                "custom_content": {
                    "attachments": [{"url": "files/bucket/a.pdf", "type": "application/pdf"}]
                },
            },
        ]

        result = policy.apply(history)
        tool_msg = result[1]
        custom_content = tool_msg.get("custom_content")
        assert isinstance(custom_content, dict)
        assert "attachments" in custom_content
