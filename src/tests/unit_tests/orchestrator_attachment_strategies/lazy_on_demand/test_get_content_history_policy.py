from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_history_policy import (
    _GetContentHistoryPolicy,
)


def _get_content_history(
    tool_content: str | None = '{"ok": true}',
    attachments: list[dict[str, str]] | None = None,
    *,
    tool_name: str = INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
    extra_custom_content: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    attachment_rows = (
        attachments
        if attachments is not None
        else [{"title": "a.pdf", "url": "files/bucket/a.pdf", "type": "application/pdf"}]
    )
    custom_content: dict[str, object] = {"attachments": attachment_rows}
    if extra_custom_content:
        custom_content.update(extra_custom_content)
    tool_msg: dict[str, object] = {
        "role": "tool",
        "tool_call_id": "tc-1",
        "custom_content": custom_content,
    }
    if tool_content is not None:
        tool_msg["content"] = tool_content
    return [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "tc-1",
                    "type": "function",
                    "function": {"name": tool_name, "arguments": "{}"},
                }
            ],
        },
        tool_msg,
    ]


class TestGetContentHistoryPolicy:
    def test_strips_attachments_but_keeps_other_custom_content_fields(self):
        policy = _GetContentHistoryPolicy()
        history = _get_content_history(extra_custom_content={"state": {"k": "v"}})

        result = policy.apply(history)
        tool_msg = result[1]
        assert "custom_content" in tool_msg
        custom_content = tool_msg["custom_content"]
        assert isinstance(custom_content, dict)
        assert "attachments" not in custom_content
        assert custom_content.get("state") == {"k": "v"}

        content = tool_msg.get("content")
        assert isinstance(content, str)
        assert '{"ok": true}' in content
        assert "<attachments>" in content
        assert "<title>a.pdf</title>" in content
        assert "<type>application/pdf</type>" in content
        assert "<url>files/bucket/a.pdf</url>" in content

    def test_appends_xml_for_multiple_attachments(self):
        policy = _GetContentHistoryPolicy()
        history = _get_content_history(
            attachments=[
                {"title": "a.pdf", "url": "files/bucket/a.pdf", "type": "application/pdf"},
                {"title": "b.csv", "url": "files/bucket/b.csv", "type": "text/csv"},
            ]
        )

        result = policy.apply(history)
        content = result[1].get("content")
        assert isinstance(content, str)
        assert "<title>a.pdf</title>" in content
        assert "<title>b.csv</title>" in content

    def test_appends_xml_when_content_missing(self):
        policy = _GetContentHistoryPolicy()
        history = _get_content_history(tool_content=None)

        result = policy.apply(history)
        content = result[1].get("content")
        assert isinstance(content, str)
        assert "<attachments>" in content
        assert "<title>a.pdf</title>" in content

    def test_leaves_message_unchanged_when_no_attachments(self):
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
                "custom_content": {"state": {"k": "v"}},
            },
        ]

        result = policy.apply(history)
        tool_msg = result[1]
        assert tool_msg.get("content") == '{"ok": true}'
        custom_content = tool_msg.get("custom_content")
        assert isinstance(custom_content, dict)
        assert custom_content.get("state") == {"k": "v"}

    def test_does_not_affect_other_tool_names(self):
        policy = _GetContentHistoryPolicy()
        history = _get_content_history(tool_name="some_other_tool")

        result = policy.apply(history)
        tool_msg = result[1]
        custom_content = tool_msg.get("custom_content")
        assert isinstance(custom_content, dict)
        assert "attachments" in custom_content
        assert tool_msg.get("content") == '{"ok": true}'
