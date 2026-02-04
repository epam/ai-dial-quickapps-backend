import json

from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.chat_completion.request import FunctionCall, ToolCall

from quickapp.config.context import FileContextConfig, UserDefinedContextConfig
from quickapp.internal_tooling.attachment_notification_tooling._tool_configs import (
    AVAILABLE_CONTEXT_TOOL_NAME,
    ContextEntry,
    extract_seen_entries_from_messages,
    has_context_tool_history,
    should_activate_context_tool,
)

TOOL_NAME = AVAILABLE_CONTEXT_TOOL_NAME


def _tool_call_pair(
    tool_name: str, entries: list[dict[str, str]], call_id: str = "call_1"
) -> list[Message]:
    """Build an assistant tool_call + tool result message pair."""
    assistant_msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                id=call_id,
                type="function",
                function=FunctionCall(name=tool_name, arguments="{}"),
            )
        ],
    )
    tool_msg = Message(
        role=Role.TOOL,
        content=json.dumps(entries, ensure_ascii=False),
        tool_call_id=call_id,
    )
    return [assistant_msg, tool_msg]


class TestExtractSeenEntriesFromMessages:
    def test_empty_messages(self):
        assert extract_seen_entries_from_messages([]) == {}

    def test_no_tool_calls(self):
        messages = [Message(role=Role.USER, content="hello")]
        assert extract_seen_entries_from_messages(messages) == {}

    def test_single_tool_result(self):
        entries = [
            {"title": "a.csv", "url": "files/bucket/a.csv", "type": "text/csv", "status": "new"},
            {
                "title": "b.pdf",
                "url": "files/bucket/b.pdf",
                "type": "application/pdf",
                "status": "new",
            },
        ]
        messages = _tool_call_pair(TOOL_NAME, entries)
        result = extract_seen_entries_from_messages(messages)
        assert set(result.keys()) == {"files/bucket/a.csv", "files/bucket/b.pdf"}
        assert result["files/bucket/a.csv"].title == "a.csv"
        assert result["files/bucket/a.csv"].type == "text/csv"
        assert result["files/bucket/b.pdf"].title == "b.pdf"
        assert result["files/bucket/b.pdf"].type == "application/pdf"

    def test_removed_entries_excluded(self):
        entries = [
            {"title": "a.csv", "url": "files/bucket/a.csv"},
            {"title": "b.pdf", "url": "files/bucket/b.pdf", "status": "removed"},
        ]
        messages = _tool_call_pair(TOOL_NAME, entries)
        result = extract_seen_entries_from_messages(messages)
        assert set(result.keys()) == {"files/bucket/a.csv"}

    def test_most_recent_result_used(self):
        entries_old = [
            {"title": "a.csv", "url": "files/bucket/a.csv", "status": "new"},
        ]
        entries_new = [
            {"title": "a.csv", "url": "files/bucket/a.csv"},
            {"title": "b.pdf", "url": "files/bucket/b.pdf", "status": "new"},
        ]
        messages = (
            _tool_call_pair(TOOL_NAME, entries_old, call_id="call_1")
            + [Message(role=Role.USER, content="next turn")]
            + _tool_call_pair(TOOL_NAME, entries_new, call_id="call_2")
        )
        result = extract_seen_entries_from_messages(messages)
        assert set(result.keys()) == {"files/bucket/a.csv", "files/bucket/b.pdf"}

    def test_wrong_tool_name_ignored(self):
        entries = [{"title": "a.csv", "url": "files/bucket/a.csv"}]
        messages = _tool_call_pair("other_tool", entries)
        result = extract_seen_entries_from_messages(messages)
        assert result == {}

    def test_malformed_json_returns_empty(self):
        assistant_msg = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(
                    id="call_bad",
                    type="function",
                    function=FunctionCall(name=TOOL_NAME, arguments="{}"),
                )
            ],
        )
        tool_msg = Message(
            role=Role.TOOL,
            content="not valid json",
            tool_call_id="call_bad",
        )
        messages = [assistant_msg, tool_msg]
        result = extract_seen_entries_from_messages(messages)
        assert result == {}

    def test_all_removed_returns_empty(self):
        entries = [
            {"title": "a.csv", "url": "files/bucket/a.csv", "status": "removed"},
        ]
        messages = _tool_call_pair(TOOL_NAME, entries)
        result = extract_seen_entries_from_messages(messages)
        assert result == {}

    def test_preserves_description(self):
        entries = [
            {
                "title": "a.csv",
                "url": "files/bucket/a.csv",
                "type": "text/csv",
                "description": "Reference data",
                "status": "new",
            },
        ]
        messages = _tool_call_pair(TOOL_NAME, entries)
        result = extract_seen_entries_from_messages(messages)
        entry = result["files/bucket/a.csv"]
        assert entry.title == "a.csv"
        assert entry.type == "text/csv"
        assert entry.description == "Reference data"


class TestHasContextToolHistory:
    def test_no_messages(self):
        assert has_context_tool_history([]) is False

    def test_user_messages_only(self):
        messages = [Message(role=Role.USER, content="hello")]
        assert has_context_tool_history(messages) is False

    def test_different_tool_name(self):
        messages = _tool_call_pair("other_tool", [])
        assert has_context_tool_history(messages) is False

    def test_matching_context_tool_call(self):
        messages = _tool_call_pair(TOOL_NAME, [{"title": "a.csv", "url": "files/a.csv"}])
        assert has_context_tool_history(messages) is True


class TestShouldActivateContextTool:
    def test_no_file_contexts_no_history(self):
        contexts = [UserDefinedContextConfig(content="some text")]
        messages: list[Message] = []
        assert should_activate_context_tool(contexts, messages) is False

    def test_empty_contexts_no_history(self):
        assert should_activate_context_tool([], []) is False

    def test_file_context_present(self):
        contexts = [FileContextConfig(url="files/bucket/a.csv")]
        assert should_activate_context_tool(contexts, []) is True

    def test_file_context_present_ignores_history(self):
        contexts = [FileContextConfig(url="files/bucket/a.csv")]
        messages = [Message(role=Role.USER, content="hello")]
        assert should_activate_context_tool(contexts, messages) is True

    def test_no_file_contexts_with_history(self):
        contexts = [UserDefinedContextConfig(content="some text")]
        messages = _tool_call_pair(TOOL_NAME, [{"title": "a.csv", "url": "files/a.csv"}])
        assert should_activate_context_tool(contexts, messages) is True
