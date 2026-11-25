import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)
from quickapp.common.time_provider import TimeProvider
from quickapp.timestamp_tooling._timestamp_metadata_enricher import _TimestampMetadataEnricher

_TEMPLATE = {"q": "${x}"}


class _TemplatedInjector(SyntheticToolCallInjector):
    def __init__(self, frequency: InjectionFrequency) -> None:
        super().__init__()
        self._frequency = frequency
        self.rendered: dict = {"q": "rendered-1"}

    async def get_tool_name(self) -> str:
        return "my_tool"

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return self._frequency

    async def get_arguments(self) -> dict:
        return _TEMPLATE

    async def get_call_arguments(self, messages: list[Message]) -> dict:
        return self.rendered

    async def get_content(self, messages: list[Message]) -> str | None:
        return "CONTENT"


class _PlainInjector(SyntheticToolCallInjector):
    async def get_tool_name(self) -> str:
        return "plain_tool"

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.ALWAYS

    async def get_arguments(self) -> dict:
        return {"a": 1}

    async def get_content(self, messages: list[Message]) -> str | None:
        return "C"


def _assistant(messages: list[Message]) -> Message:
    return next(m for m in messages if m.role == Role.ASSISTANT)


def _displayed_arguments(messages: list[Message]) -> dict:
    tool_calls = _assistant(messages).tool_calls
    assert tool_calls is not None
    return json.loads(tool_calls[0].function.arguments)


def _call_id(messages: list[Message]) -> str:
    tool_calls = _assistant(messages).tool_calls
    assert tool_calls is not None
    return tool_calls[0].id


_USER = [Message(role=Role.USER, content="hi")]


class TestGetCallArguments:
    @pytest.mark.asyncio
    async def test_default_equals_get_arguments(self) -> None:
        injector = _PlainInjector()
        assert await injector.get_call_arguments(_USER) == {"a": 1}

    @pytest.mark.asyncio
    async def test_default_displays_get_arguments(self) -> None:
        result = await _PlainInjector().transform(list(_USER))
        assert _displayed_arguments(result) == {"a": 1}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "frequency", [InjectionFrequency.ALWAYS, InjectionFrequency.APPEND_IF_CHANGED]
    )
    async def test_displays_rendered_arguments_but_identity_uses_template(
        self, frequency: InjectionFrequency
    ) -> None:
        injector = _TemplatedInjector(frequency)
        result = await injector.transform(list(_USER))

        assert _displayed_arguments(result) == {"q": "rendered-1"}
        assert _call_id(result).startswith(injector._make_call_id_prefix("my_tool", _TEMPLATE))

    @pytest.mark.asyncio
    async def test_in_place_replace_updates_displayed_arguments(self) -> None:
        injector = _TemplatedInjector(InjectionFrequency.APPEND_IF_CHANGED)
        first = await injector.transform(list(_USER))

        injector.rendered = {"q": "rendered-2"}
        second = await injector.transform(first)

        assert len(second) == len(first)
        assert _call_id(second) == _call_id(first)
        assert _displayed_arguments(second) == {"q": "rendered-2"}


class _AdvancingClock(TimeProvider):
    def __init__(self) -> None:
        super().__init__()
        self._tick = 0

    def now(self) -> datetime:
        self._tick += 1
        return datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")) + timedelta(minutes=self._tick)


class _StampedInjector(_PlainInjector):
    def __init__(self, enrichers: list[ToolCallResultEnricher]) -> None:
        provider = MagicMock()
        provider.get.return_value = enrichers
        super().__init__(provider)

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.APPEND_IF_CHANGED


class TestIdenticalPairStaysStable:
    @pytest.mark.asyncio
    async def test_identical_pair_is_not_restamped_on_next_turn(self) -> None:
        injector = _StampedInjector([_TimestampMetadataEnricher(_AdvancingClock())])

        first = await injector.transform(list(_USER))
        second = await injector.transform(first)

        assert second is first
        assert second[2].custom_content is not None
