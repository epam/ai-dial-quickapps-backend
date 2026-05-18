from aidial_sdk.chat_completion.request import Message, Role


def tool_function_name_for_tool_message(messages: list[Message], index: int) -> str | None:
    """Resolve OpenAI function name for a TOOL message from the preceding assistant tool_calls."""
    if index < 0 or index >= len(messages):
        return None
    msg = messages[index]
    if msg.role != Role.TOOL:
        return None
    tool_call_id = msg.tool_call_id
    if not tool_call_id:
        return None

    for i in range(index - 1, -1, -1):
        prev = messages[i]
        if prev.role != Role.ASSISTANT or not prev.tool_calls:
            continue
        for tc in prev.tool_calls:
            if tc.id == tool_call_id and tc.function is not None:
                return tc.function.name

    return None
