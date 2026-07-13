import json

from quickapp.common.file_reference_pattern import to_file_url_reference
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_history_policy import (
    _GetContentHistoryPolicy,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_tool_response import (
    HISTORY_ATTACHMENT_REMOVED_STATUS_MESSAGE,
    GetContentStatus,
    GetContentToolResponse,
)


def _get_content_history(
    *,
    tool_content: str | None = None,
    tool_state: dict[str, object] | None = None,
    attachments: list[dict[str, str]] | None = None,
    tool_name: str = INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
    tool_arguments: str | None = None,
    extra_custom_content: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    attachment_rows = (
        attachments
        if attachments is not None
        else [{"title": "a.pdf", "url": "files/bucket/a.pdf", "type": "application/pdf"}]
    )
    display_url = attachment_rows[0]["url"]
    response = GetContentToolResponse.success(
        display_url=display_url,
        title=attachment_rows[0]["title"],
        mime_type=attachment_rows[0]["type"],
    )
    if tool_content is None or tool_state is None:
        built_content, state_fragment = response.tool_parts()
        tool_content = built_content if tool_content is None else tool_content
        tool_state = state_fragment if tool_state is None else tool_state
    custom_content: dict[str, object] = {"attachments": attachment_rows, "state": tool_state}
    if extra_custom_content:
        custom_content.update(extra_custom_content)
    tool_msg: dict[str, object] = {
        "role": "tool",
        "tool_call_id": "tc-1",
        "custom_content": custom_content,
        "content": tool_content,
    }
    if tool_arguments is None:
        tool_arguments = json.dumps({"attachment_url": to_file_url_reference(display_url)})
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


class TestGetContentHistoryPolicy:
    def test_strips_attachments_and_rewrites_content_with_status_message(self):
        policy = _GetContentHistoryPolicy()
        history = _get_content_history(extra_custom_content={"state": {"k": "v"}})

        result = policy.apply(history)
        tool_msg = result[1]
        assert "custom_content" in tool_msg
        custom_content = tool_msg["custom_content"]
        assert isinstance(custom_content, dict)
        assert "attachments" not in custom_content
        state = custom_content.get("state")
        assert isinstance(state, dict)
        assert state.get("k") == "v"

        payload = GetContentToolResponse.from_state(state)
        assert payload is not None
        assert payload.status == GetContentStatus.SUCCESS
        assert payload.attachment_url == to_file_url_reference("files/bucket/a.pdf")
        assert payload.title == "a.pdf"
        assert payload.type == "application/pdf"
        assert payload.status_message == HISTORY_ATTACHMENT_REMOVED_STATUS_MESSAGE
        assert tool_msg.get("content") == payload.content_summary()

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
        state = result[1]["custom_content"]["state"]
        payload = GetContentToolResponse.from_state(state)
        assert payload is not None
        assert payload.attachment_url == explicit_url
        assert payload.status_message == HISTORY_ATTACHMENT_REMOVED_STATUS_MESSAGE

    def test_rewrites_content_for_multiple_attachments_using_first_attachment(self):
        policy = _GetContentHistoryPolicy()
        history = _get_content_history(
            attachments=[
                {"title": "a.pdf", "url": "files/bucket/a.pdf", "type": "application/pdf"},
                {"title": "b.csv", "url": "files/bucket/b.csv", "type": "text/csv"},
            ],
            tool_arguments="{}",
        )

        result = policy.apply(history)
        payload = GetContentToolResponse.from_state(result[1]["custom_content"]["state"])
        assert payload is not None
        assert payload.attachment_url == to_file_url_reference("files/bucket/a.pdf")

    def test_leaves_message_unchanged_when_no_attachments(self):
        policy = _GetContentHistoryPolicy()
        response = GetContentToolResponse.success(
            display_url="files/bucket/a.pdf",
            title="a.pdf",
            mime_type="application/pdf",
        )
        content, state_fragment = response.tool_parts()
        state = {"k": "v", **state_fragment}
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
                "content": content,
                "custom_content": {"state": state},
            },
        ]

        result = policy.apply(history)
        tool_msg = result[1]
        assert tool_msg.get("content") == content
        custom_content = tool_msg.get("custom_content")
        assert isinstance(custom_content, dict)
        assert custom_content.get("state") == state

    def test_does_not_affect_other_tool_names(self):
        policy = _GetContentHistoryPolicy()
        history = _get_content_history(tool_name="some_other_tool")

        result = policy.apply(history)
        tool_msg = result[1]
        custom_content = tool_msg.get("custom_content")
        assert isinstance(custom_content, dict)
        assert "attachments" in custom_content
        payload = GetContentToolResponse.from_state(custom_content.get("state"))
        assert payload is not None
        assert payload.status_message is None
