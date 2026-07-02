import json

from quickapp.common.file_reference_pattern import to_file_url_reference
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_history_policy import (
    _build_attachment_removed_notice,
    _GetContentHistoryPolicy,
)


def _expected_notice(*attachment_urls: str) -> str:
    return _build_attachment_removed_notice(list(attachment_urls))


def _get_content_history(
    tool_content: str | None = '{"ok": true}',
    attachments: list[dict[str, str]] | None = None,
    *,
    tool_name: str = INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
    tool_arguments: str | None = None,
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
    if tool_arguments is None:
        tool_arguments = json.dumps(
            {"attachment_url": to_file_url_reference(attachment_rows[0]["url"])}
        )
    return [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "tc-1",
                    "type": "function",
                    "function": {"name": tool_name, "arguments": tool_arguments},
                }
            ],
        },
        tool_msg,
    ]


class TestBuildAttachmentRemovedNotice:
    def test_includes_tool_name_and_copy_pasteable_arguments(self):
        url = to_file_url_reference("files/bucket/a.pdf")
        notice = _build_attachment_removed_notice([url])
        assert INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME in notice
        assert json.dumps({"attachment_url": url}, ensure_ascii=False) in notice
        assert "page-level or verbatim content" in notice


class TestGetContentHistoryPolicy:
    def test_strips_attachments_but_keeps_other_custom_content_fields(self):
        policy = _GetContentHistoryPolicy()
        url = to_file_url_reference("files/bucket/a.pdf")
        history = _get_content_history(extra_custom_content={"state": {"k": "v"}})

        result = policy.apply(history)
        tool_msg = result[1]
        assert "custom_content" in tool_msg
        custom_content = tool_msg["custom_content"]
        assert isinstance(custom_content, dict)
        assert "attachments" not in custom_content
        assert custom_content.get("state") == {"k": "v"}
        assert tool_msg.get("content") == '{"ok": true}\n' + _expected_notice(url)

    def test_builds_file_url_reference_from_attachment_when_tool_args_missing(self):
        policy = _GetContentHistoryPolicy()
        url = to_file_url_reference("files/bucket/a.pdf")
        history = _get_content_history(tool_arguments="{}")

        result = policy.apply(history)
        assert result[1].get("content") == '{"ok": true}\n' + _expected_notice(url)

    def test_prefers_attachment_url_from_assistant_tool_call_arguments(self):
        policy = _GetContentHistoryPolicy()
        explicit_url = to_file_url_reference("files/bucket/from-args.pdf")
        history = _get_content_history(
            attachments=[
                {"title": "a.pdf", "url": "files/bucket/a.pdf", "type": "application/pdf"}
            ],
            tool_arguments=json.dumps({"attachment_url": explicit_url}),
        )

        result = policy.apply(history)
        assert result[1].get("content") == '{"ok": true}\n' + _expected_notice(explicit_url)

    def test_appends_notice_for_multiple_attachments(self):
        policy = _GetContentHistoryPolicy()
        url_a = to_file_url_reference("files/bucket/a.pdf")
        url_b = to_file_url_reference("files/bucket/b.csv")
        history = _get_content_history(
            attachments=[
                {"title": "a.pdf", "url": "files/bucket/a.pdf", "type": "application/pdf"},
                {"title": "b.csv", "url": "files/bucket/b.csv", "type": "text/csv"},
            ],
            tool_arguments="{}",
        )

        result = policy.apply(history)
        content = result[1].get("content")
        assert isinstance(content, str)
        assert content.startswith('{"ok": true}\n')
        notice = content.split("\n", 1)[1]
        assert notice == _expected_notice(url_a, url_b)

    def test_appends_notice_when_original_content_missing(self):
        policy = _GetContentHistoryPolicy()
        url = to_file_url_reference("files/bucket/a.pdf")
        history = _get_content_history(tool_content=None)

        result = policy.apply(history)
        assert result[1].get("content") == "\n" + _expected_notice(url)

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
