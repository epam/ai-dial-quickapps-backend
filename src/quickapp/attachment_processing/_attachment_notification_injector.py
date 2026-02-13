import json
import logging
import uuid

from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.chat_completion.request import FunctionCall, ToolCall
from injector import ProviderOf, inject

from quickapp.attachment_processing._context_entries import (
    AvailableContextToolResponse,
    build_context_entries,
    extract_seen_entries_from_messages,
    should_activate_context_tool,
)
from quickapp.attachment_processing._tool_configs import AVAILABLE_CONTEXT_TOOL_NAME
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.config.application import ApplicationConfig
from quickapp.config.context import Context

logger = logging.getLogger(__name__)


class _AttachmentNotificationInjector(MessagesTransformer):
    """Injects synthetic tool call/result messages to inform the agent about
    available contexts when changes are detected."""

    @inject
    def __init__(self, config_provider: ProviderOf[ApplicationConfig]):
        self.__config_provider: ProviderOf[ApplicationConfig] = config_provider

    def transform(self, messages: list[Message]) -> list[Message]:
        contexts = list(self.__config_provider.get().contexts)

        if not isinstance(messages, list):
            raise TypeError("Data must be a list of Message objects")

        if not should_activate_context_tool(contexts, messages):
            return messages

        synthetic: list[Message] = self._check_contexts(messages, contexts)

        if not synthetic:
            return messages

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Injecting {len(synthetic)} synthetic messages for context notification: "
                f"{[str(msg) for msg in synthetic]}"
            )

        return messages + synthetic

    def _check_contexts(self, messages: list[Message], contexts: list[Context]) -> list[Message]:
        """Collect context file metadata and return synthetic messages if changed."""
        seen_entries = extract_seen_entries_from_messages(messages)
        current_urls, entries = build_context_entries(contexts, seen_entries)
        tool_response = AvailableContextToolResponse(entries=entries)

        if current_urls == set(seen_entries) and not any(e.status for e in entries):
            return []

        return self._build_synthetic_messages(
            AVAILABLE_CONTEXT_TOOL_NAME,
            json.dumps(tool_response.model_dump(exclude_none=True), ensure_ascii=False),
        )

    @staticmethod
    def _build_synthetic_messages(tool_name: str, content: str) -> list[Message]:
        """Build a pair of assistant tool_call + tool result messages."""
        call_id = f"synthetic_{uuid.uuid4().hex[:12]}"
        assistant_msg = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(
                    id=call_id,
                    type="function",
                    function=FunctionCall(name=tool_name, arguments="{}"),
                )
            ],
        )
        tool_msg = Message(
            role=Role.TOOL,
            content=content,
            tool_call_id=call_id,
        )
        return [assistant_msg, tool_msg]
