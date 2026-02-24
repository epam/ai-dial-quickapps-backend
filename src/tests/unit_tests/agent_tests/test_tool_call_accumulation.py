"""Test script to verify tool call accumulation works correctly."""

import pytest
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall, ChoiceDeltaToolCallFunction

from quickapp.agent.chunk_processor import AccumulatedToolCall, AssistantCallResult


def test_tool_call_accumulation():
    """Test that tool calls are accumulated correctly from deltas."""
    result = AssistantCallResult()

    # Simulate the streaming deltas shown in the logs
    delta1 = ChoiceDeltaToolCall(
        index=0,
        id='chatcmpl-tool-a89453224f0a3994',
        function=ChoiceDeltaToolCallFunction(arguments=None, name='geo_code_de9a'),
        type='function'
    )

    delta2 = ChoiceDeltaToolCall(
        index=0,
        id=None,
        function=ChoiceDeltaToolCallFunction(arguments='{"q": "', name=None),
        type=None
    )

    delta3 = ChoiceDeltaToolCall(
        index=0,
        id=None,
        function=ChoiceDeltaToolCallFunction(arguments='NY', name=None),
        type=None
    )

    delta4 = ChoiceDeltaToolCall(
        index=0,
        id=None,
        function=ChoiceDeltaToolCallFunction(arguments='"}', name=None),
        type=None
    )

    # Apply all deltas
    result.append_tool_call_delta(delta1)
    result.append_tool_call_delta(delta2)
    result.append_tool_call_delta(delta3)
    result.append_tool_call_delta(delta4)

    # Verify accumulated tool calls
    tool_calls = result.tool_calls
    assert tool_calls is not None
    assert len(tool_calls) == 1

    tc = tool_calls[0]
    assert tc.id == 'chatcmpl-tool-a89453224f0a3994'
    assert tc.name == 'geo_code_de9a'
    assert tc.arguments == '{"q": "NY"}'



def test_multiple_tool_calls_accumulation():
    """Test accumulation of multiple parallel tool calls."""
    result = AssistantCallResult()

    # First tool call - delta with id
    result.append_tool_call_delta(ChoiceDeltaToolCall(
        index=0,
        id='call-1',
        function=ChoiceDeltaToolCallFunction(arguments=None, name='tool_a'),
        type='function'
    ))
    # Second tool call - delta with id
    result.append_tool_call_delta(ChoiceDeltaToolCall(
        index=1,
        id='call-2',
        function=ChoiceDeltaToolCallFunction(arguments=None, name='tool_b'),
        type='function'
    ))
    # Arguments for the first tool call
    result.append_tool_call_delta(ChoiceDeltaToolCall(
        index=0,
        id=None,
        function=ChoiceDeltaToolCallFunction(arguments='{"x": 1}', name=None),
        type=None
    ))
    # Arguments for the second tool call
    result.append_tool_call_delta(ChoiceDeltaToolCall(
        index=1,
        id=None,
        function=ChoiceDeltaToolCallFunction(arguments='{"y": 2}', name=None),
        type=None
    ))

    tool_calls = result.tool_calls
    assert tool_calls is not None
    assert len(tool_calls) == 2

    assert tool_calls[0].id == 'call-1'
    assert tool_calls[0].name == 'tool_a'
    assert tool_calls[0].arguments == '{"x": 1}'

    assert tool_calls[1].id == 'call-2'
    assert tool_calls[1].name == 'tool_b'
    assert tool_calls[1].arguments == '{"y": 2}'


def test_no_tool_calls_returns_none():
    """Test that tool_calls returns None when no deltas have been appended."""
    result = AssistantCallResult()
    assert result.tool_calls is None


def test_accessing_id_before_set_raises():
    """Test that accessing id before it has been accumulated raises ValueError."""
    tc = AccumulatedToolCall()
    with pytest.raises(ValueError, match="id has not been received"):
        _ = tc.id


def test_accessing_name_before_set_raises():
    """Test that accessing a name before it has been accumulated raises ValueError."""
    tc = AccumulatedToolCall()
    with pytest.raises(ValueError, match="name has not been received"):
        _ = tc.name


def test_accessing_arguments_before_set_raises():
    """Test that accessing arguments before they have been accumulated raises ValueError."""
    tc = AccumulatedToolCall()
    with pytest.raises(ValueError, match="arguments have not been received"):
        _ = tc.arguments


def test_arguments_accumulated_across_deltas():
    """Test that arguments are correctly concatenated across multiple deltas."""
    tc = AccumulatedToolCall()
    tc.append_delta(ChoiceDeltaToolCall(
        index=0, id='c1',
        function=ChoiceDeltaToolCallFunction(arguments=None, name='f'),
        type='function'
    ))
    # arguments still None at this point
    with pytest.raises(ValueError):
        _ = tc.arguments

    tc.append_delta(ChoiceDeltaToolCall(
        index=0, id=None,
        function=ChoiceDeltaToolCallFunction(arguments='{"a":', name=None),
        type=None
    ))
    assert tc.arguments == '{"a":'

    tc.append_delta(ChoiceDeltaToolCall(
        index=0, id=None,
        function=ChoiceDeltaToolCallFunction(arguments=' 1}', name=None),
        type=None
    ))
    assert tc.arguments == '{"a": 1}'


