from aidial_sdk.chat_completion import Attachment
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

from .accumulated_tool_call import AccumulatedToolCall


class Usage:
    def __init__(self, prompt_tokens: int, completion_tokens: int):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class AssistantCallResult:
    def __init__(self):
        self.__content = ""
        self.__attachments: list[Attachment] = []
        self.__accumulated_tool_calls: dict[int, AccumulatedToolCall] = {}
        self.__usage: Usage | None = None

    @property
    def content(self):
        return self.__content

    def append_content(self, content: str) -> None:
        self.__content += content

    @property
    def attachments(self):
        return self.__attachments

    def append_attachment(self, attachment: Attachment) -> None:
        self.__attachments.append(attachment)

    @property
    def tool_calls(self) -> list[AccumulatedToolCall] | None:
        values = list(self.__accumulated_tool_calls.values())
        return values if values else None

    def append_tool_call_delta(self, tool_call_delta: ChoiceDeltaToolCall) -> None:
        index = tool_call_delta.index
        if index not in self.__accumulated_tool_calls:
            self.__accumulated_tool_calls[index] = AccumulatedToolCall()
        self.__accumulated_tool_calls[index].append_delta(tool_call_delta)

    @property
    def usage(self):
        return self.__usage

    def set_usage(self, usage: Usage) -> None:
        self.__usage = usage
