import json

from aidial_sdk.chat_completion import FunctionCall, ToolCall
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

from quickapp.common.file_reference_pattern import strip_file_prefix


class AccumulatedToolCall:
    _REPR_ARGS_MAX_LEN = 120

    def __init__(self) -> None:
        self._id: str | None = None
        self._name: str | None = None
        self._arguments: str | None = None

    def __repr__(self) -> str:
        id_str = self._id if self._id is not None else "<pending>"
        name_str = self._name if self._name is not None else "<pending>"
        args_preview: str
        if self._arguments is None:
            args_preview = "<pending>"
        elif len(self._arguments) <= self._REPR_ARGS_MAX_LEN:
            args_preview = self._arguments
        else:
            args_preview = f"{self._arguments[:self._REPR_ARGS_MAX_LEN]}..."
        return f"AccumulatedToolCall(id={id_str!r}, name={name_str!r}, arguments={args_preview!r})"

    @property
    def id(self) -> str:
        if self._id is None:
            raise ValueError("Tool call id has not been received yet")
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

    def to_sdk_tool_call(self):
        raw_args = self.arguments
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    if isinstance(v, str):
                        parsed[k] = strip_file_prefix(v)
                    elif isinstance(v, list):
                        parsed[k] = [
                            strip_file_prefix(item) if isinstance(item, str) else item for item in v
                        ]
                raw_args = json.dumps(parsed)
        except (json.JSONDecodeError, TypeError):
            pass
        return ToolCall(
            id=self.id,
            type="function",
            function=FunctionCall(name=self.name, arguments=raw_args),
        )

    @staticmethod
    def to_sdk_tool_calls(tool_calls: list["AccumulatedToolCall"] | None) -> list[ToolCall] | None:
        if tool_calls is None:
            return None
        return [tc.to_sdk_tool_call() for tc in tool_calls]
