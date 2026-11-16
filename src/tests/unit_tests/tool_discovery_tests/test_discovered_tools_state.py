from aidial_sdk.chat_completion import CustomContent, Message, Role

from quickapp.tool_discovery._discovered_tools_state import (
    DISCOVERED_TOOLS_STATE_KEY,
    read_discovered_tool_names,
)


def _assistant(state: dict | None) -> Message:
    return Message(
        role=Role.ASSISTANT,
        content="ok",
        custom_content=CustomContent(state=state) if state is not None else None,
    )


def test_returns_names_from_latest_assistant_message_with_the_key() -> None:
    messages = [
        _assistant({DISCOVERED_TOOLS_STATE_KEY: ["a"]}),
        Message(role=Role.USER, content="next"),
        _assistant({DISCOVERED_TOOLS_STATE_KEY: ["a", "b"]}),
        Message(role=Role.USER, content="again"),
    ]

    assert read_discovered_tool_names(messages) == ["a", "b"]


def test_ignores_messages_without_the_key() -> None:
    messages = [
        _assistant({DISCOVERED_TOOLS_STATE_KEY: ["a"]}),
        _assistant({"other": 1}),
        _assistant(None),
    ]

    assert read_discovered_tool_names(messages) == ["a"]


def test_empty_list_in_latest_message_is_authoritative() -> None:
    messages = [
        _assistant({DISCOVERED_TOOLS_STATE_KEY: ["a"]}),
        _assistant({DISCOVERED_TOOLS_STATE_KEY: []}),
    ]

    assert read_discovered_tool_names(messages) == []


def test_malformed_value_yields_nothing() -> None:
    assert read_discovered_tool_names([_assistant({DISCOVERED_TOOLS_STATE_KEY: "a"})]) == []
    assert read_discovered_tool_names([_assistant({DISCOVERED_TOOLS_STATE_KEY: ["a", 1, ""]})]) == [
        "a"
    ]


def test_no_assistant_messages() -> None:
    assert read_discovered_tool_names([Message(role=Role.USER, content="hi")]) == []
