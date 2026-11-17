from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role

from quickapp.core.agent.lazy_loaded_tools_holder import DISCOVERED_TOOLS_STATE_KEY
from quickapp.tool_discovery._discovered_tools_state_stripper import _DiscoveredToolsStateStripper


def _transform(message: Message) -> Message:
    return _DiscoveredToolsStateStripper().transform([message])[0]


def test_removes_key_and_keeps_other_state() -> None:
    message = Message(
        role=Role.ASSISTANT,
        content="ok",
        custom_content=CustomContent(state={DISCOVERED_TOOLS_STATE_KEY: ["a"], "other": 1}),
    )

    result = _transform(message)

    assert result.custom_content is not None
    assert result.custom_content.state == {"other": 1}


def test_canonical_message_is_not_mutated() -> None:
    message = Message(
        role=Role.ASSISTANT,
        content="ok",
        custom_content=CustomContent(state={DISCOVERED_TOOLS_STATE_KEY: ["a"]}),
    )

    _transform(message)

    assert message.custom_content is not None
    assert message.custom_content.state == {DISCOVERED_TOOLS_STATE_KEY: ["a"]}


def test_drops_emptied_custom_content() -> None:
    message = Message(
        role=Role.ASSISTANT,
        content="ok",
        custom_content=CustomContent(state={DISCOVERED_TOOLS_STATE_KEY: ["a"]}),
    )

    assert _transform(message).custom_content is None


def test_keeps_attachments_when_state_is_emptied() -> None:
    attachment = Attachment(type="text/plain", url="files/x")
    message = Message(
        role=Role.ASSISTANT,
        content="ok",
        custom_content=CustomContent(
            state={DISCOVERED_TOOLS_STATE_KEY: ["a"]}, attachments=[attachment]
        ),
    )

    result = _transform(message)

    assert result.custom_content is not None
    assert result.custom_content.state is None
    assert result.custom_content.attachments == [attachment]


def test_messages_without_the_key_are_returned_as_is() -> None:
    plain = Message(role=Role.USER, content="hi")
    with_state = Message(
        role=Role.ASSISTANT, content="ok", custom_content=CustomContent(state={"other": 1})
    )

    assert _DiscoveredToolsStateStripper().transform([plain, with_state]) == [plain, with_state]
