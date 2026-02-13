import logging
from typing import Any, Dict, Optional

from aidial_sdk.chat_completion import Choice, Stage
from aidial_sdk.chat_completion.request import ToolCall
from injector import inject
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

from quickapp.common.dial_core_client import Attachment


class Usage:
    def __init__(self, prompt_tokens: int, completion_tokens: int):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class AssistantCallResult:
    def __init__(self):
        self.__content = ""
        self.__attachments: list[Attachment] = []
        self.__tool_calls: Dict[int, ToolCall] = {}
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
        values = list(self.__tool_calls.values())
        return values if values else None

    def append_tool_call_delta(self, tool_call_delta: ChoiceDeltaToolCall) -> None:
        if tool_call_delta.id:
            tool_call = ToolCall(**tool_call_delta.dict())
            self.__tool_calls[tool_call_delta.index] = tool_call
        else:
            tool_call = self.__tool_calls[tool_call_delta.index]
            if tool_call_delta.function:
                argument_chunk = tool_call_delta.function.arguments or ''
                tool_call.function.arguments += argument_chunk

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
