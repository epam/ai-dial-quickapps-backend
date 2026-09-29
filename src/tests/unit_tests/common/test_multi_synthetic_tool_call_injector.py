import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.synthetic_injection.multi_synthetic_tool_call_injector import (
    MultiSyntheticToolCallInjector,
    SyntheticCall,
)
from quickapp.common.tool_call_result import ToolCallResult
from tests.unit_tests.common.common import make_provider

# ---------------------------------------------------------------------------
# Minimal concrete implementation for testing
# ---------------------------------------------------------------------------


class _FixedCallsInjector(MultiSyntheticToolCallInjector):
    """Injects whatever ``calls``/``contents`` it was built with, in order.
    ``contents`` is looked up by index at ``get_content`` time, so a test can
    mutate it between two ``transform`` calls to simulate changed content."""

    def __init__(
        self,
        calls: list[SyntheticCall],
        contents: list[str],
        enrichers: list[ToolCallResultEnricher] | None = None,
    ):
        super().__init__(make_provider(enrichers) if enrichers else None)
        self.calls = calls
        self.contents = contents

    async def get_calls(self, messages: list[Message]) -> list[SyntheticCall]:
        return self.calls

    async def get_content(self, call: SyntheticCall, index: int, messages: list[Message]) -> str:
        return self.contents[index]


def _user(content: str = "hi") -> Message:
    return Message(role=Role.USER, content=content)


def _call(tool_name: str = "tool_a", **arguments: object) -> SyntheticCall:
    return SyntheticCall(tool_name=tool_name, arguments=arguments)


class TestNoCalls:
    @pytest.mark.asyncio
    async def test_empty_calls_leaves_messages_unchanged(self):
        injector = _FixedCallsInjector([], [])
        messages = [_user()]

        assert await injector.transform(messages) == messages


class TestFirstInjection:
    @pytest.mark.asyncio
    async def test_one_assistant_message_carries_all_parallel_calls(self):
        injector = _FixedCallsInjector(
            [_call("tool_a", x=1), _call("tool_b", y=2)], ["content a", "content b"]
        )
        messages = [_user()]

        result = await injector.transform(messages)

        assert [m.role for m in result] == [Role.USER, Role.ASSISTANT, Role.TOOL, Role.TOOL]
        assistant = result[1]
        assert len(assistant.tool_calls) == 2
        assert assistant.tool_calls[0].function.name == "tool_a"
        assert assistant.tool_calls[1].function.name == "tool_b"
        assert result[2].content == "content a"
        assert result[3].content == "content b"
        assert result[2].tool_call_id == assistant.tool_calls[0].id
        assert result[3].tool_call_id == assistant.tool_calls[1].id

    @pytest.mark.asyncio
    async def test_turn_is_inserted_after_the_first_user_message(self):
        injector = _FixedCallsInjector([_call()], ["content"])
        messages = [
            _user("first"),
            Message(role=Role.ASSISTANT, content="reply"),
            _user("second"),
        ]

        result = await injector.transform(messages)

        assert [m.role for m in result] == [
            Role.USER,
            Role.ASSISTANT,
            Role.TOOL,
            Role.ASSISTANT,
            Role.USER,
        ]


class TestNoOpWhenUnchanged:
    @pytest.mark.asyncio
    async def test_re_running_with_the_same_set_and_content_is_a_no_op(self):
        injector = _FixedCallsInjector(
            [_call("tool_a", x=1), _call("tool_b", y=2)], ["content a", "content b"]
        )
        first = await injector.transform([_user()])

        second = await injector.transform(first)

        assert second == first


class TestAppendWhenContentChanges:
    @pytest.mark.asyncio
    async def test_same_set_with_changed_content_appends_a_fresh_copy_at_the_end(self):
        injector = _FixedCallsInjector([_call("tool_a", x=1)], ["v1"])
        first = await injector.transform([_user()])
        assert len(first) == 3

        injector.contents = ["v2"]
        second = await injector.transform(first)

        # The v1 turn is left where it is; a fresh v2 turn is appended at the end.
        assert len(second) == 5
        assert second[0] is first[0]
        assert second[1] == first[1]
        assert second[2] == first[2]
        assert second[3].role == Role.ASSISTANT
        assert second[4].role == Role.TOOL
        assert second[4].content == "v2"
        assert second[4].tool_call_id != second[2].tool_call_id

    @pytest.mark.asyncio
    async def test_a_different_set_never_collides_with_an_earlier_occurrence(self):
        injector = _FixedCallsInjector([_call("tool_a", x=1)], ["content"])
        first = await injector.transform([_user()])

        different_set_injector = _FixedCallsInjector([_call("tool_a", x=2)], ["content"])
        second = await different_set_injector.transform(first)

        # Both turns coexist: the sets differ (different arguments), so the second
        # is a fresh insertion, not treated as a re-occurrence of the first.
        assert len(second) == 5


class TestEnrichment:
    @pytest.mark.asyncio
    async def test_enriched_state_lands_on_every_synthetic_tool_message(self):
        class _StampingEnricher(ToolCallResultEnricher):
            def enrich(self, result: ToolCallResult) -> None:
                result.state = {"marker": "seen"}

        injector = _FixedCallsInjector(
            [_call("tool_a", x=1), _call("tool_b", y=2)],
            ["content a", "content b"],
            enrichers=[_StampingEnricher()],
        )

        result = await injector.transform([_user()])

        assert result[2].custom_content.state == {"marker": "seen"}
        assert result[3].custom_content.state == {"marker": "seen"}


class TestCustomCallIdPrefix:
    @pytest.mark.asyncio
    async def test_custom_prefix_applied_to_every_call_id(self):
        class _PrefixedInjector(_FixedCallsInjector):
            call_id_prefix = "my_prefix_"

        injector = _PrefixedInjector([_call("tool_a"), _call("tool_b")], ["a", "b"])

        result = await injector.transform([_user()])

        assert result[1].tool_calls[0].id.startswith("my_prefix_")
        assert result[1].tool_calls[1].id.startswith("my_prefix_")


class TestPayloadCarriesConsumerData:
    @pytest.mark.asyncio
    async def test_get_content_reads_payload_instead_of_relying_on_index(self):
        class _PayloadEchoInjector(MultiSyntheticToolCallInjector):
            async def get_calls(self, messages: list[Message]) -> list[SyntheticCall]:
                return [
                    SyntheticCall(tool_name="tool_a", arguments={}, payload="alpha"),
                    SyntheticCall(tool_name="tool_a", arguments={}, payload="beta"),
                ]

            async def get_content(
                self, call: SyntheticCall, index: int, messages: list[Message]
            ) -> str:
                return f"resolved:{call.payload}"

        result = await _PayloadEchoInjector().transform([_user()])

        assert {result[2].content, result[3].content} == {"resolved:alpha", "resolved:beta"}
