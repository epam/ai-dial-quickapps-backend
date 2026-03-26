from .accumulated_tool_call import AccumulatedToolCall


def __getattr__(name: str):
    if name == "ChatStreamAccumulator":
        from quickapp.common.chat_completion_stream.stream_result import ChatStreamAccumulator

        return ChatStreamAccumulator
    if name == "Usage":
        from quickapp.common.chat_completion_stream.stream_result import Usage

        return Usage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["AccumulatedToolCall", "ChatStreamAccumulator", "Usage"]
