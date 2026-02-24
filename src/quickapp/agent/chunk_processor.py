import logging
from typing import Any, Dict, Optional

from aidial_sdk.chat_completion import Attachment, Choice, FunctionCall, Stage, ToolCall
from injector import inject
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall


class Usage:
    def __init__(self, prompt_tokens: int, completion_tokens: int):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class AccumulatedToolCall:
    def __init__(self) -> None:
        self._id: str | None = None
        self._name: str | None = None
        self._arguments: str | None = None

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
            raise ValueError("Tool call arguments have not been received yet")
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


class AssistantCallResult:
    def __init__(self):
        self.__content = ""
        self.__attachments: list[Attachment] = []
        self.__accumulated_tool_calls: Dict[int, AccumulatedToolCall] = {}
        self.__usage: Optional[Usage] = None

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


logger = logging.getLogger(__name__)


@inject
class ChunkProcessor:

    def __init__(self):
        self.__assistant_call_result = AssistantCallResult()

    async def process_chunks(
        self,
        chat_completion: AsyncStream[ChatCompletionChunk],
        destination: Choice,
        stream_content: bool = True,
    ) -> AssistantCallResult | None:
        destination.append_content("\n\r")

        async for chunk in chat_completion:
            if not chunk.choices:
                continue
            for ch in chunk.choices:
                if (content := ch.delta.content) and stream_content:
                    destination.append_content(content)
                    self.__assistant_call_result.append_content(content)

                if custom_content := getattr(ch.delta, 'custom_content', None):
                    self.__process_custom_content(custom_content, destination)

                if tool_calls_deltas_list := getattr(ch.delta, 'tool_calls', None):
                    for delta in tool_calls_deltas_list:
                        self.__assistant_call_result.append_tool_call_delta(delta)
            if chunk.usage:
                self.__assistant_call_result.set_usage(
                    Usage(
                        prompt_tokens=chunk.usage.prompt_tokens,
                        completion_tokens=chunk.usage.completion_tokens,
                    )
                )
        self.__log_assistant_call_result(self.__assistant_call_result)
        return self.__assistant_call_result

    def __process_custom_content(
        self, custom_content: dict[str, Any], destination: Choice | Stage
    ) -> None:
        if attachments := custom_content.get('attachments'):
            for attachment in attachments:
                # bugfix issue#16 - if attachment has no data and no url, but has reference_url, use it as url
                if attachment.get('data') is None and attachment.get('url') is None:
                    if attachment.get('reference_url') is None:
                        attachment['data'] = ''
                    else:
                        attachment['url'] = attachment.get('reference_url')
                destination.add_attachment(
                    type=attachment.get('type'),
                    title=attachment.get('title'),
                    data=attachment.get('data'),
                    url=attachment.get('url'),
                    reference_url=attachment.get('reference_url'),
                    reference_type=attachment.get('reference_type'),
                )
                self.__assistant_call_result.append_attachment(attachment)

    @staticmethod
    def __log_assistant_call_result(result: AssistantCallResult) -> None:
        logger.debug("===================")
        logger.debug(" ---- Captured values:")
        logger.debug(f" ----- text llm response: {result.content}")
        if result.tool_calls:
            logger.debug(" ------ tool_calls:")
            for tool in result.tool_calls:
                logger.debug(f" -------- {tool.name} - {tool.arguments} - {tool}")

        if result.attachments:
            logger.debug(f" ------ attachments: {result.attachments}")

        logger.debug("===================")
