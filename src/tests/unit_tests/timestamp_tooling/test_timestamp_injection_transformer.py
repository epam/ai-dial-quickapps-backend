from types import SimpleNamespace
from unittest.mock import Mock

from aidial_sdk.chat_completion import Message, Role

from quickapp.common.time_provider import TimeProvider
from quickapp.config.timestamp import ToolCallTimestampConfig
from quickapp.timestamp_tooling._timestamp_injection_transformer import (
    _TimestampInjectionTransformer,
)
from quickapp.timestamp_tooling._tool_configs import (
    CURRENT_TIMESTAMP_TOOL_NAME,
    SYNTHETIC_TIMESTAMP_CALL_PREFIX,
)


def _make_config_provider(enabled: bool = True) -> Mock:
    features = SimpleNamespace(timestamp=ToolCallTimestampConfig() if enabled else None)
    config = SimpleNamespace(features=features)
    provider = Mock()
    provider.get.return_value = config
    return provider


def _make_transformer(enabled: bool = True) -> _TimestampInjectionTransformer:
    return _TimestampInjectionTransformer(
        time_provider=TimeProvider(),
        config_provider=_make_config_provider(enabled),
    )


class TestTimestampInjectionTransformer:
    def test_appends_two_synthetic_messages(self):
        transformer = _make_transformer()
        messages = [Message(role=Role.USER, content="hello")]

        result = transformer.transform(messages)

        assert len(result) == 3
        assert result[0] is messages[0]
        assert result[1].role == Role.ASSISTANT
        assert result[2].role == Role.TOOL

    def test_synthetic_call_id_has_correct_prefix(self):
        transformer = _make_transformer()
        result = transformer.transform([Message(role=Role.USER, content="hi")])

        assistant_msg = result[1]
        tool_msg = result[2]

        call_id = assistant_msg.tool_calls[0].id
        assert call_id.startswith(SYNTHETIC_TIMESTAMP_CALL_PREFIX)
        assert tool_msg.tool_call_id == call_id

    def test_tool_name_matches_config(self):
        transformer = _make_transformer()
        result = transformer.transform([Message(role=Role.USER, content="hi")])

        assistant_msg = result[1]
        assert assistant_msg.tool_calls[0].function.name == CURRENT_TIMESTAMP_TOOL_NAME

    def test_content_contains_iso_timestamp(self):
        transformer = _make_transformer()
        result = transformer.transform([Message(role=Role.USER, content="hi")])

        tool_msg = result[2]
        content = str(tool_msg.content)
        assert "UTC" in content
        assert "source=default" in content
        assert "T" in content

    def test_does_not_modify_original_messages(self):
        transformer = _make_transformer()
        original = [Message(role=Role.USER, content="hi")]
        result = transformer.transform(original)

        assert len(original) == 1
        assert len(result) == 3

    def test_empty_messages_returns_empty(self):
        transformer = _make_transformer()
        messages: list[Message] = []
        result = transformer.transform(messages)

        assert result is messages

    def test_noop_when_feature_disabled(self):
        transformer = _make_transformer(enabled=False)
        messages = [Message(role=Role.USER, content="hi")]
        result = transformer.transform(messages)

        assert result is messages
