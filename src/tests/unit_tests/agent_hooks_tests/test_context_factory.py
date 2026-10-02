from types import SimpleNamespace

from aidial_sdk.chat_completion import (
    Message,
    MessageContentImagePart,
    MessageContentTextPart,
    Role,
)
from aidial_sdk.chat_completion.request import FunctionCall, ImageURL, ToolCall

from quickapp.agent_hooks._context_factory import HookContextFactory
from tests.unit_tests.common.common import make_provider


def _factory(messages: list[Message] | None = None) -> tuple[HookContextFactory, object]:
    provider = make_provider(SimpleNamespace(messages=messages or []))
    return HookContextFactory(provider), provider


def _tool_call(call_id: str, name: str, arguments: str) -> ToolCall:
    return ToolCall(
        id=call_id, type="function", function=FunctionCall(name=name, arguments=arguments)
    )


class TestRequestStart:
    def test_converts_user_text(self) -> None:
        factory, _ = _factory()
        ctx = factory.request_start([Message(role=Role.USER, content="hello")])

        assert ctx.event == "on_request_start"
        assert ctx.messages[0].role == "user"
        assert ctx.messages[0].content == "hello"
        assert ctx.last_user_message is not None

    def test_does_not_touch_the_provider(self) -> None:
        factory, provider = _factory()
        factory.request_start([Message(role=Role.USER, content="hello")])
        provider.get.assert_not_called()  # type: ignore[attr-defined]

    def test_multimodal_content_keeps_only_text_parts_joined_by_newline(self) -> None:
        factory, _ = _factory()
        message = Message(
            role=Role.USER,
            content=[
                MessageContentTextPart(type="text", text="first"),
                MessageContentImagePart(
                    type="image_url", image_url=ImageURL(url="http://example.com/i.png")
                ),
                MessageContentTextPart(type="text", text="second"),
            ],
        )
        ctx = factory.request_start([message])
        assert ctx.messages[0].content == "first\nsecond"

    def test_whitespace_only_content_becomes_empty_string(self) -> None:
        factory, _ = _factory()
        ctx = factory.request_start([Message(role=Role.USER, content="  \n ")])
        assert ctx.messages[0].content == ""

    def test_none_content_stays_none(self) -> None:
        factory, _ = _factory()
        message = Message(
            role=Role.ASSISTANT, content=None, tool_calls=[_tool_call("c1", "t", "{}")]
        )
        ctx = factory.request_start([message])
        assert ctx.messages[0].content is None

    def test_tool_calls_are_parsed(self) -> None:
        factory, _ = _factory()
        message = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[_tool_call("c1", "read_file", '{"file_path": "/a.txt", "n": 2}')],
        )
        ctx = factory.request_start([message])

        call = ctx.messages[0].tool_calls[0]
        assert (call.id, call.name) == ("c1", "read_file")
        assert call.arguments == {"file_path": "/a.txt", "n": 2}

    def test_malformed_or_non_object_arguments_become_empty_dict(self) -> None:
        factory, _ = _factory()
        message = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                _tool_call("c1", "t", "{not json"),
                _tool_call("c2", "t", "[1, 2]"),
                _tool_call("c3", "t", ""),
            ],
        )
        ctx = factory.request_start([message])
        assert [c.arguments for c in ctx.messages[0].tool_calls] == [{}, {}, {}]

    def test_tool_message_keeps_tool_call_id(self) -> None:
        factory, _ = _factory()
        ctx = factory.request_start([Message(role=Role.TOOL, content="out", tool_call_id="c1")])
        assert ctx.messages[0].role == "tool"
        assert ctx.messages[0].tool_call_id == "c1"


class TestCompletion:
    def test_reads_messages_from_provider_and_carries_counters(self) -> None:
        factory, provider = _factory(
            [
                Message(role=Role.USER, content="q"),
                Message(role=Role.ASSISTANT, content="answer"),
            ]
        )
        ctx = factory.completion(iteration_count=2, total_tool_calls=3)

        provider.get.assert_called_once()  # type: ignore[attr-defined]
        assert ctx.event == "on_completion"
        assert (ctx.iteration_count, ctx.total_tool_calls) == (2, 3)
        assert ctx.last_assistant_message is not None
        assert ctx.last_assistant_message.content == "answer"
