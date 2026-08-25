from aidial_sdk.chat_completion import FunctionCall, ToolCall
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall


class AccumulatedToolCall:
    def __init__(self) -> None:
        self._id: str | None = None
        self._name: str | None = None
        self._arguments: str | None = None

    def __str__(self) -> str:
        return f"AccumulatedToolCall(id={self._id}, name={self._name}, arguments={self._arguments})"

    @property
    def id(self) -> str:
        if self._id is None:
            raise ValueError("Tool call id has not been received yet")
        return self._id

    @property
    def id_or_none(self) -> str | None:
        return self._id

    @property
    def name(self) -> str:
        if self._name is None:
            raise ValueError("Tool call name has not been received yet")
        return self._name

    @property
    def arguments(self) -> str:
        if self._arguments is None:
            return "{}"
        return self._arguments

    def append_delta(self, delta: ChoiceDeltaToolCall) -> None:
        def append_field(current: str | None, chunk: str | None) -> str | None:
            if chunk is None:
                return current
            return chunk if current is None else current + chunk

        self._id = append_field(self._id, delta.id)
        if delta.function:
            self._name = append_field(self._name, delta.function.name)
            self._arguments = append_field(self._arguments, delta.function.arguments)

    def to_sdk_tool_call(self) -> ToolCall:
        return ToolCall(
            id=self.id,
            type="function",
            function=FunctionCall(name=self.name, arguments=self.arguments),
        )

    @staticmethod
    def to_sdk_tool_calls(tool_calls: list["AccumulatedToolCall"] | None) -> list[ToolCall] | None:
        if tool_calls is None:
            return None
        return [tc.to_sdk_tool_call() for tc in tool_calls]
