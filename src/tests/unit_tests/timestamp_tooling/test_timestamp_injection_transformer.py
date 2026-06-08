from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.message_metadata import get_metadata_from_state
from quickapp.common.time_provider import TimeProvider
from quickapp.config.timestamp import ToolCallTimestampConfig
from quickapp.timestamp_tooling._timestamp_injection_transformer import (
    _TimestampInjectionTransformer,
)
from quickapp.timestamp_tooling._timestamp_metadata_enricher import _TimestampMetadataEnricher
from quickapp.timestamp_tooling._tool_configs import (
    CURRENT_TIMESTAMP_TOOL_NAME,
    SYNTHETIC_TIMESTAMP_CALL_PREFIX,
)
from tests.unit_tests.common.common import make_provider


def _make_config_provider(enabled: bool = True) -> Mock:
    features = SimpleNamespace(timestamp=ToolCallTimestampConfig() if enabled else None)
    config = SimpleNamespace(features=features)
    provider = Mock()
    provider.get.return_value = config
    return provider


def _make_transformer(
    enabled: bool = True,
    enrichers: list[ToolCallResultEnricher] | None = None,
) -> _TimestampInjectionTransformer:
    return _TimestampInjectionTransformer(
        time_provider=TimeProvider(),
        config_provider=_make_config_provider(enabled),
        enrichers_provider=make_provider(enrichers if enrichers is not None else []),
    )


class TestTimestampInjectionTransformer:
    @pytest.mark.asyncio
    async def test_appends_two_synthetic_messages(self):
        transformer = _make_transformer()
        messages = [Message(role=Role.USER, content="hello")]

        result = await transformer.transform(messages)

        assert len(result) == 3
        assert result[0] is messages[0]
        assert result[1].role == Role.ASSISTANT
        assert result[2].role == Role.TOOL

    @pytest.mark.asyncio
    async def test_synthetic_call_id_has_correct_prefix(self):
        transformer = _make_transformer()
        result = await transformer.transform([Message(role=Role.USER, content="hi")])

        assistant_msg = result[1]
        tool_msg = result[2]

        call_id = assistant_msg.tool_calls[0].id
        assert call_id.startswith(SYNTHETIC_TIMESTAMP_CALL_PREFIX)
        assert tool_msg.tool_call_id == call_id

    @pytest.mark.asyncio
    async def test_tool_name_matches_config(self):
        transformer = _make_transformer()
        result = await transformer.transform([Message(role=Role.USER, content="hi")])

        assistant_msg = result[1]
        assert assistant_msg.tool_calls[0].function.name == CURRENT_TIMESTAMP_TOOL_NAME

    @pytest.mark.asyncio
    async def test_content_contains_iso_timestamp(self):
        transformer = _make_transformer()
        result = await transformer.transform([Message(role=Role.USER, content="hi")])

        tool_msg = result[2]
        content = str(tool_msg.content)
        assert "UTC" in content
        assert "source=default" in content
        assert "T" in content

    @pytest.mark.asyncio
    async def test_does_not_modify_original_messages(self):
        transformer = _make_transformer()
        original = [Message(role=Role.USER, content="hi")]
        result = await transformer.transform(original)

        assert len(original) == 1
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_empty_messages_returns_empty(self):
        transformer = _make_transformer()
        messages: list[Message] = []
        result = await transformer.transform(messages)

        assert result is messages

    @pytest.mark.asyncio
    async def test_noop_when_feature_disabled(self):
        transformer = _make_transformer(enabled=False)
        messages = [Message(role=Role.USER, content="hi")]
        result = await transformer.transform(messages)

        assert result is messages

    @pytest.mark.asyncio
    async def test_synthetic_tool_message_carries_enriched_metadata(self):
        transformer = _make_transformer(
            enrichers=[_TimestampMetadataEnricher(TimeProvider())],
        )
        result = await transformer.transform([Message(role=Role.USER, content="hi")])

        tool_msg = result[2]
        assert tool_msg.custom_content is not None
        metadata = get_metadata_from_state(tool_msg.custom_content.state)
        assert metadata is not None
        assert metadata.timestamp is not None
        assert metadata.timestamp.response_timestamp is not None
        assert metadata.timestamp.timezone_name == "UTC"

    @pytest.mark.asyncio
    async def test_synthetic_tool_message_has_no_state_without_enrichers(self):
        transformer = _make_transformer()
        result = await transformer.transform([Message(role=Role.USER, content="hi")])

        tool_msg = result[2]
        assert tool_msg.custom_content is None
