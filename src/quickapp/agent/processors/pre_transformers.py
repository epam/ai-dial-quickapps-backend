import copy
import json
import logging
import mimetypes
import uuid
from abc import ABC, abstractmethod
from typing import Any, Optional

from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role
from aidial_sdk.chat_completion.request import FunctionCall, ToolCall
from pydantic.v1 import StrictStr

from quickapp.agent.models import TOOL_EXECUTION_HISTORY, ExecutedToolCallDTO
from quickapp.common.utils import matches_type, sanitize_toolname
from quickapp.config.context import Context, FileContextConfig

logger = logging.getLogger(__name__)


class PreTransformer(ABC):
    @abstractmethod
    def transform(self, input_param: Any): ...


class AddSystemPromptTransformer(PreTransformer):

    def __init__(self, system_prompt: Optional[str], instructions: Optional[str] = None):
        parts = (system_prompt or "", instructions or "")
        self._combined_system_prompt = "\n\n".join(p for p in parts if p)

    def transform(self, messages: list[Message]):
        if not isinstance(messages, list):
            raise TypeError("Data must be a list of Message objects")
        if not self._combined_system_prompt:
            return messages
        if len(messages) > 0 and messages[0].role != Role.SYSTEM:
            return [
                Message(role=Role.SYSTEM, content=StrictStr(self._combined_system_prompt))
            ] + messages

        return messages


class RemoveStateTransformer(PreTransformer):
    def transform(self, input_param: list[Message]):
        # Validate input is List[Message]
        if not isinstance(input_param, list):
            raise TypeError("Data must be a list of Message objects")
        for item in input_param:
            if not isinstance(item, Message):
                raise TypeError("All items must be Message instances")
            if item.custom_content:
                item.custom_content.state = None  # Remove all state temp data
        return input_param


class ReduceAttachmentTransformer(PreTransformer):
    SUPPORTED_ATTACHMENTS = ["image/*"]

    def transform(self, input_param: list[Message]):
        # Validate input is List[Message]
        if not isinstance(input_param, list):
            raise TypeError("Data must be a list of Message objects")
        for item in input_param:
            if not isinstance(item, Message):
                raise TypeError("All items must be Message instances")
            self._transform_item(item)
        return input_param

    def _transform_item(self, message: Message):
        updated_attachments = []
        if message.content is None:
            message.content = StrictStr("")
        if message.custom_content is not None and message.custom_content.attachments:
            for attachment in message.custom_content.attachments:
                if message.role == Role.USER and matches_type(
                    attachment.type, self.SUPPORTED_ATTACHMENTS
                ):
                    updated_attachments.append(attachment)
                # Inform agent that message had contained some attachment.
                # As adapter would resolve the actual bytes and URL would be lost.
                message.content += (
                    f"\n\rAttachment {attachment.title}, of type {attachment.type}, "
                    f"url {attachment.url}, reference_url {attachment.reference_url}\n\r"
                )
            message.custom_content.attachments = updated_attachments

        return message


class ExtractToolCallsFromStateProcessor(PreTransformer):

    def transform(self, messages: list[Message]) -> list[Message]:
        """
        unpack "ASSISTANT" message with stages (tool calls) into new messages with role "TOOL" for proper
        history of LLM calls.
        """

        updated_messages = []
        for message in messages:
            custom_content = message.custom_content
            if (
                message.role == Role.ASSISTANT
                and custom_content
                and custom_content.state
                and (tool_history := custom_content.state.get(TOOL_EXECUTION_HISTORY)) is not None
            ):
                assistant_message = copy.deepcopy(message)
                if assistant_message.custom_content and assistant_message.custom_content.state:
                    assistant_message.custom_content.state.pop(TOOL_EXECUTION_HISTORY, None)

                for history_part in tool_history:
                    executed_tool_call = ExecutedToolCallDTO.validate(history_part)
                    assistant_tool_call = copy.deepcopy(assistant_message)
                    assistant_tool_call.content = StrictStr("")

                    if assistant_tool_call.tool_calls is None:
                        assistant_tool_call.tool_calls = []
                    if (
                        executed_tool_call not in assistant_tool_call.tool_calls
                    ):  # TODO: check, seems it should be `executed_tool_call.tool_call`
                        assistant_tool_call.tool_calls.append(executed_tool_call.tool_call)

                    updated_messages.append(assistant_tool_call)
                    updated_messages.append(executed_tool_call.tool_execution_result)

                updated_messages.append(assistant_message)
            else:
                updated_messages.append(message)

        return updated_messages


class AddContextAttachmentTransformer(PreTransformer):

    def __init__(self, contexts: list[Context]):
        self.contexts = contexts

    def transform(self, messages: list[Message]) -> list[Message]:
        if messages and messages[-1].role == Role.USER:
            self.__append_context_files_to_last_message(messages[-1])
        return messages

    def __append_context_files_to_last_message(self, last_msg: Message):
        if self.contexts:
            for ctx in self.contexts:
                if isinstance(ctx, FileContextConfig):
                    title = ctx.url.rsplit('/', 1)[-1]
                    if not last_msg.custom_content:
                        last_msg.custom_content = CustomContent(attachments=[])
                    last_msg.custom_content.attachments.append(
                        Attachment(
                            type=StrictStr(mimetypes.guess_type(title)[0]),
                            url=StrictStr(ctx.url),
                            title=StrictStr(title),
                        )
                    )
                    logger.debug(f"File {ctx.url} added to the message.")


class AttachmentNotificationInjector(PreTransformer):
    """Injects synthetic tool call/result messages to inform the agent about
    available contexts when changes are detected."""

    def __init__(
        self,
        context_tool_name: str,
        contexts: list[Context],
    ):
        self._context_tool_name = sanitize_toolname(context_tool_name)
        self._contexts = contexts
        self._seen_context_urls: set[str] = set()

    def transform(self, messages: list[Message]) -> list[Message]:
        if not isinstance(messages, list):
            raise TypeError("Data must be a list of Message objects")

        synthetic: list[Message] = self._check_contexts()

        if not synthetic:
            return messages

        return messages + synthetic

    def _check_contexts(self) -> list[Message]:
        """Collect context file metadata and return synthetic messages if changed."""
        current_urls: set[str] = set()
        entries: list[dict[str, str]] = []

        for ctx in self._contexts:
            if not isinstance(ctx, FileContextConfig):
                continue
            url = ctx.url
            if url in current_urls:
                continue
            current_urls.add(url)
            title = url.rsplit("/", 1)[-1]
            mime_type = mimetypes.guess_type(title)[0] or ""
            entry: dict[str, str] = {
                "title": title,
                "url": url,
                "type": mime_type,
            }
            if ctx.description:
                entry["description"] = ctx.description
            if url not in self._seen_context_urls:
                entry["status"] = "new"
            entries.append(entry)

        if current_urls == self._seen_context_urls:
            return []

        self._seen_context_urls = current_urls
        if not entries:
            return []

        return self._build_synthetic_messages(
            self._context_tool_name, json.dumps(entries, ensure_ascii=False)
        )

    @staticmethod
    def _build_synthetic_messages(tool_name: str, content: str) -> list[Message]:
        """Build a pair of assistant tool_call + tool result messages."""
        call_id = f"synthetic_{uuid.uuid4().hex[:12]}"
        assistant_msg = Message(
            role=Role.ASSISTANT,
            content=StrictStr(""),
            tool_calls=[
                ToolCall(
                    id=StrictStr(call_id),
                    type="function",
                    function=FunctionCall(name=tool_name, arguments="{}"),
                )
            ],
        )
        tool_msg = Message(
            role=Role.TOOL,
            content=StrictStr(content),
            tool_call_id=StrictStr(call_id),
        )
        return [assistant_msg, tool_msg]
