import json
from unittest.mock import MagicMock

import pytest
from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.chat_completion.request import FunctionCall, ToolCall

from quickapp.common.tool_names import INTERNAL_MCP_READ_RESOURCE_TOOL_NAME
from quickapp.mcp_tooling._mcp_eager_resource import MCPEagerTextResource
from quickapp.mcp_tooling._mcp_eager_resource_transformer import (
    _after_first_user_idx,
    _already_injected_pairs,
    _build_synthetic_pair,
    _MCPEagerResourceTransformer,
)


def _user_msg(text: str = "hello") -> Message:
    return Message(role=Role.USER, content=text)


def _assistant_msg(content: str = "") -> Message:
    return Message(role=Role.ASSISTANT, content=content)


def _read_resource_call(uri: str, toolset: str = "") -> Message:
    args = json.dumps({"uri": uri, "toolset": toolset})
    return Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                id="tc1",
                type="function",
                function=FunctionCall(
                    name=INTERNAL_MCP_READ_RESOURCE_TOOL_NAME,
                    arguments=args,
                ),
            )
        ],
    )


def _eager(uri: str, toolset: str = "ts", text: str = "content") -> MCPEagerTextResource:
    return MCPEagerTextResource(
        toolset_name=toolset,
        toolset_description=None,
        resource_name="res",
        resource_uri=uri,
        text=text,
    )


def _make_context(eager: list[MCPEagerTextResource]) -> MagicMock:
    ctx = MagicMock()
    ctx.eager_resources = eager
    return ctx


# --- Unit tests for pure helpers ---


def test_after_first_user_idx_returns_one_after_first_user():
    messages = [_assistant_msg(), _user_msg(), _assistant_msg()]
    assert _after_first_user_idx(messages) == 2


def test_after_first_user_idx_no_user_returns_len():
    messages = [_assistant_msg(), _assistant_msg()]
    assert _after_first_user_idx(messages) == 2


def test_after_first_user_idx_empty():
    assert _after_first_user_idx([]) == 0


def test_already_injected_pairs_finds_read_resource_calls():
    msg = _read_resource_call("urn://res", "ts1")
    seen = _already_injected_pairs([msg])
    assert ("urn://res", "ts1") in seen


def test_already_injected_pairs_ignores_other_tool_calls():
    msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                id="x",
                type="function",
                function=FunctionCall(name="other_tool", arguments='{"uri": "urn://res"}'),
            )
        ],
    )
    assert _already_injected_pairs([msg]) == set()


def test_already_injected_pairs_skips_malformed_json():
    msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                id="x",
                type="function",
                function=FunctionCall(
                    name=INTERNAL_MCP_READ_RESOURCE_TOOL_NAME, arguments="{not valid json"
                ),
            )
        ],
    )
    assert _already_injected_pairs([msg]) == set()


def test_already_injected_pairs_ignores_non_assistant_messages():
    msg = _user_msg()
    assert _already_injected_pairs([msg]) == set()


def test_build_synthetic_pair_structure():
    assistant_msg, tool_msg = _build_synthetic_pair("urn://x", "ts", "hello")

    assert assistant_msg.role == Role.ASSISTANT
    assert assistant_msg.tool_calls is not None
    assert len(assistant_msg.tool_calls) == 1
    tc = assistant_msg.tool_calls[0]
    assert tc.function.name == INTERNAL_MCP_READ_RESOURCE_TOOL_NAME
    args = json.loads(tc.function.arguments)
    assert args["uri"] == "urn://x"
    assert args["toolset"] == "ts"

    assert tool_msg.role == Role.TOOL
    assert tool_msg.content == "hello"
    assert tool_msg.tool_call_id == tc.id


# --- Integration tests for the transformer ---


@pytest.mark.asyncio
async def test_transform_no_eager_resources_is_noop():
    transformer = _MCPEagerResourceTransformer(_make_context([]))
    messages = [_user_msg()]
    result = await transformer.transform(messages)
    assert result is messages


@pytest.mark.asyncio
async def test_transform_injects_pair_after_first_user_message():
    resource = _eager("urn://doc", "ts", "doc content")
    transformer = _MCPEagerResourceTransformer(_make_context([resource]))

    messages = [_user_msg("hi")]
    result = await transformer.transform(messages)

    # Should be: user, assistant (synth call), tool (synth result)
    assert len(result) == 3
    assert result[0].role == Role.USER
    assert result[1].role == Role.ASSISTANT
    assert result[2].role == Role.TOOL
    assert result[2].content == "doc content"


@pytest.mark.asyncio
async def test_transform_inserts_after_first_user_not_end():
    resource = _eager("urn://doc", "ts", "text")
    transformer = _MCPEagerResourceTransformer(_make_context([resource]))

    messages = [_assistant_msg("sys"), _user_msg("q"), _assistant_msg("a"), _user_msg("q2")]
    result = await transformer.transform(messages)

    # Pair inserted after first user (index 1), so: sys, user, assistant(synth), tool(synth), assistant, user
    assert result[0].role == Role.ASSISTANT  # sys
    assert result[1].role == Role.USER  # first user
    assert result[2].role == Role.ASSISTANT  # synth call
    assert result[3].role == Role.TOOL  # synth result
    assert result[4].role == Role.ASSISTANT  # original a
    assert result[5].role == Role.USER  # q2


@pytest.mark.asyncio
async def test_transform_skips_already_injected_on_second_turn():
    resource = _eager("urn://doc", "ts", "text")
    transformer = _MCPEagerResourceTransformer(_make_context([resource]))

    # Simulate second turn: history already has the synthetic call
    existing_call = _read_resource_call("urn://doc", "ts")
    existing_result = Message(role=Role.TOOL, content="text", tool_call_id="tc1")
    messages = [_user_msg("q1"), existing_call, existing_result, _user_msg("q2")]

    result = await transformer.transform(messages)
    assert result == messages  # no new messages added


@pytest.mark.asyncio
async def test_transform_multiple_resources_all_injected():
    r1 = _eager("urn://a", "ts1", "a text")
    r2 = _eager("urn://b", "ts2", "b text")
    transformer = _MCPEagerResourceTransformer(_make_context([r1, r2]))

    messages = [_user_msg()]
    result = await transformer.transform(messages)

    # 1 user + 2 pairs = 5 messages
    assert len(result) == 5
    tool_contents = [m.content for m in result if m.role == Role.TOOL]
    assert set(tool_contents) == {"a text", "b text"}


@pytest.mark.asyncio
async def test_transform_same_uri_different_toolsets_both_injected():
    r1 = _eager("urn://shared", "ts1", "from ts1")
    r2 = _eager("urn://shared", "ts2", "from ts2")
    transformer = _MCPEagerResourceTransformer(_make_context([r1, r2]))

    messages = [_user_msg()]
    result = await transformer.transform(messages)

    assert len(result) == 5  # user + 2 pairs
    tool_contents = [m.content for m in result if m.role == Role.TOOL]
    assert "from ts1" in tool_contents
    assert "from ts2" in tool_contents


@pytest.mark.asyncio
async def test_transform_duplicate_resource_injected_once():
    # Same (uri, toolset) appears twice in eager list — dedup within one turn
    r = _eager("urn://x", "ts", "text")
    transformer = _MCPEagerResourceTransformer(_make_context([r, r]))

    messages = [_user_msg()]
    result = await transformer.transform(messages)

    assert len(result) == 3  # user + 1 pair (not 2)


@pytest.mark.asyncio
async def test_transform_no_user_message_appends_at_end():
    resource = _eager("urn://doc", "ts", "text")
    transformer = _MCPEagerResourceTransformer(_make_context([resource]))

    messages = [_assistant_msg("sys")]
    result = await transformer.transform(messages)

    # No user found → insert_idx = len(messages) = 1, so pair goes at end
    assert result[0].role == Role.ASSISTANT  # original sys
    assert result[1].role == Role.ASSISTANT  # synth call
    assert result[2].role == Role.TOOL  # synth result


@pytest.mark.asyncio
async def test_transform_partially_seen_resource_only_new_injected():
    r1 = _eager("urn://a", "ts1", "a text")
    r2 = _eager("urn://b", "ts2", "b text")
    transformer = _MCPEagerResourceTransformer(_make_context([r1, r2]))

    # r1 already in history
    existing_call = _read_resource_call("urn://a", "ts1")
    messages = [_user_msg(), existing_call]
    result = await transformer.transform(messages)

    # Only r2 should be injected
    new_tool_msgs = [m for m in result if m.role == Role.TOOL]
    assert len(new_tool_msgs) == 1
    assert new_tool_msgs[0].content == "b text"
