"""Test script to verify tool call accumulation works correctly."""
import sys

from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall, ChoiceDeltaToolCallFunction

from quickapp.agent.chunk_processor import AssistantCallResult

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
    print("Applying delta 1...")
    result.append_tool_call_delta(delta1)

    print("Applying delta 2...")
    result.append_tool_call_delta(delta2)

    print("Applying delta 3...")
    result.append_tool_call_delta(delta3)

    print("Applying delta 4...")
    result.append_tool_call_delta(delta4)

    # Get the final tool calls
    tool_calls = result.tool_calls

    print("\n=== Results ===")
    if tool_calls:
        for tool_call in tool_calls:
            print(f"Tool Call ID: {tool_call.id}")
            print(f"Type: {tool_call.type}")
            print(f"Function Name: {tool_call.function.name}")
            print(f"Function Arguments: {tool_call.function.arguments}")

            # Verify expected values
            assert tool_call.id == 'chatcmpl-tool-a89453224f0a3994'
            assert tool_call.type == 'function'
            assert tool_call.function.name == 'geo_code_de9a'
            assert tool_call.function.arguments == '{"q": "NY"}'

        print("\n✓ Test passed! Tool call accumulated correctly.")
    else:
        print("✗ Test failed! No tool calls found.")
        sys.exit(1)

if __name__ == "__main__":
    test_tool_call_accumulation()

