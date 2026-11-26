"""``form_source_tool_name_before`` — resolves the tool whose form the client is filling."""

from aidial_sdk.chat_completion import Message

from quickapp.common.form_utils import (
    find_tool_conversation_mode,
    form_source_tool_name_before,
    is_resumable,
    last_user_form_value_index,
)


def _assistant_with_call(tool_call_id: str, name: str) -> Message:
    return Message.model_validate(
        {
            "role": "assistant",
            "content": "calling",
            "tool_calls": [
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": "{}"},
                }
            ],
        }
    )


def _tool_with_schema(tool_call_id: str, schema=None) -> Message:
    return Message.model_validate(
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": "result",
            "custom_content": {"form_schema": schema if schema is not None else {"type": "object"}},
        }
    )


def _user(content="hi") -> Message:
    return Message(role="user", content=content)


def test_no_form_in_history_returns_none():
    assert form_source_tool_name_before([_user()], 1) is None


def test_single_form_resolves_to_its_tool():
    msgs = [_user(), _assistant_with_call("tc-1", "tool_a"), _tool_with_schema("tc-1")]
    assert form_source_tool_name_before(msgs, len(msgs)) == "tool_a"


def test_two_forms_in_same_turn_first_wins():
    """Orchestrator sends only the first form_schema of a turn (SDK: one per choice)."""
    msgs = [
        _user(),
        _assistant_with_call("tc-1", "tool_a"),
        _tool_with_schema("tc-1"),
        _assistant_with_call("tc-2", "tool_b"),
        _tool_with_schema("tc-2"),
    ]
    assert form_source_tool_name_before(msgs, len(msgs)) == "tool_a"


def test_latest_turn_wins_across_turns():
    """A newer turn's form supersedes an older one."""
    msgs = [
        _user("first"),
        _assistant_with_call("tc-1", "tool_a"),
        _tool_with_schema("tc-1"),
        _user("second"),
        _assistant_with_call("tc-2", "tool_b"),
        _tool_with_schema("tc-2"),
    ]
    assert form_source_tool_name_before(msgs, len(msgs)) == "tool_b"


def test_older_turn_used_when_latest_has_no_form():
    msgs = [
        _user("first"),
        _assistant_with_call("tc-1", "tool_a"),
        _tool_with_schema("tc-1"),
        _user("second"),
        _assistant_with_call("tc-2", "tool_b"),
        Message.model_validate({"role": "tool", "tool_call_id": "tc-2", "content": "no form here"}),
    ]
    assert form_source_tool_name_before(msgs, len(msgs)) == "tool_a"


def test_index_limits_scan_to_prefix():
    msgs = [
        _user(),
        _assistant_with_call("tc-1", "tool_a"),
        _tool_with_schema("tc-1"),
        _user("after"),
    ]
    # index=3 excludes the trailing user message but includes the form
    assert form_source_tool_name_before(msgs, 3) == "tool_a"
    # index=1: only the first user message — no form yet
    assert form_source_tool_name_before(msgs, 1) is None


def test_empty_schema_dict_still_counts_as_form():
    msgs = [_user(), _assistant_with_call("tc-1", "tool_a"), _tool_with_schema("tc-1", schema={})]
    assert form_source_tool_name_before(msgs, len(msgs)) == "tool_a"


class TestFindToolConversationMode:
    def test_matches_by_runtime_tool_name(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        tool = MagicMock()
        tool.openai_function_name.return_value = "my_tool"
        tool.tool_config.conversation_mode = SimpleNamespace(resumable=True)

        assert find_tool_conversation_mode([tool], "my_tool").resumable is True

    def test_unknown_tool_returns_none(self):
        from unittest.mock import MagicMock

        assert find_tool_conversation_mode([], "nope") is None
        assert find_tool_conversation_mode([MagicMock()], None) is None

    def test_tool_without_conversation_mode(self):
        from unittest.mock import MagicMock

        tool = MagicMock()
        tool.openai_function_name.return_value = "t"
        tool.tool_config.conversation_mode = None

        assert find_tool_conversation_mode([tool], "t") is None
        assert is_resumable(find_tool_conversation_mode([tool], "t")) is False


def test_is_resumable_typed():
    from types import SimpleNamespace

    assert is_resumable(SimpleNamespace(resumable=True)) is True
    assert is_resumable(SimpleNamespace(resumable=False)) is False
    assert is_resumable(None) is False


def test_tool_only_history_shape():
    """Real history shape: assistant with tool_calls (no schema) + tool message with schema."""
    msgs = [
        _user(),
        _assistant_with_call("tc-1", "tool_a"),
        _tool_with_schema("tc-1"),
    ]
    assert form_source_tool_name_before(msgs, len(msgs)) == "tool_a"


def test_latest_turn_wins_real_shape():
    msgs = [
        _user("one"),
        _assistant_with_call("tc-1", "tool_a"),
        _tool_with_schema("tc-1"),
        _user("two"),
        _assistant_with_call("tc-2", "tool_b"),
        _tool_with_schema("tc-2"),
    ]
    assert form_source_tool_name_before(msgs, len(msgs)) == "tool_b"
