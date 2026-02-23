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


class AssistantCallResult:
    def __init__(self):
        self.__content = ""
        self.__attachments: list[Attachment] = []
        self.__tool_calls_data: Dict[int, Dict[str, Any]] = {}
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
    def tool_calls(self):
        if not self.__tool_calls_data:
            return None

        # Convert accumulated dict data to ToolCall objects
        tool_calls = []
        for data in self.__tool_calls_data.values():
            tool_calls.append(
                ToolCall(
                    id=data['id'],
                    type=data['type'],
                    function=FunctionCall(
                        name=data['function']['name'], arguments=data['function']['arguments']
                    ),
                )
            )
        return tool_calls

    def append_tool_call_delta(self, tool_call_delta: ChoiceDeltaToolCall) -> None:
        index = tool_call_delta.index

        # Initialize tool call data if this is the first delta (has id)
        if tool_call_delta.id:
            self.__tool_calls_data[index] = {
                'id': tool_call_delta.id,
                'type': tool_call_delta.type,
                'function': {
                    'name': tool_call_delta.function.name if tool_call_delta.function else None,
                    'arguments': '',
                },
            }
        else:
            # Update existing tool call data
            if index in self.__tool_calls_data:
                if tool_call_delta.function:
                    if tool_call_delta.function.name:
                        self.__tool_calls_data[index]['function'][
                            'name'
                        ] = tool_call_delta.function.name
                    if tool_call_delta.function.arguments:
                        self.__tool_calls_data[index]['function'][
                            'arguments'
                        ] += tool_call_delta.function.arguments

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
                logger.debug(f" -------- {tool.function.name} - {tool.function.arguments} - {tool}")

        if result.attachments:
            logger.debug(f" ------ attachments: {result.attachments}")

        logger.debug("===================")
