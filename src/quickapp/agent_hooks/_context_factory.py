import json
from typing import Any

from aidial_sdk.chat_completion import Message, MessageContentTextPart, Role
from aidial_sdk.chat_completion.request import ToolCall
from injector import ProviderOf, inject

from quickapp.common.hook_context.context import (
    CompletionHookContext,
    HookMessage,
    HookToolCall,
    RequestStartHookContext,
)
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.config.hooks import HookEvent


@inject
class HookContextFactory:
    """Builds frozen hook contexts from the request's DIAL messages."""

    def __init__(self, messages_provider: ProviderOf[MessagesMixin]) -> None:
        self._messages_provider = messages_provider

    @staticmethod
    def request_start(messages: list[Message]) -> RequestStartHookContext:
        return RequestStartHookContext(
            event=HookEvent.ON_REQUEST_START.value,
            messages=[_to_hook_message(m) for m in messages],
        )

    def completion(self, *, iteration_count: int, total_tool_calls: int) -> CompletionHookContext:
        messages = self._messages_provider.get().messages
        return CompletionHookContext(
            event=HookEvent.ON_COMPLETION.value,
            messages=[_to_hook_message(m) for m in messages],
            iteration_count=iteration_count,
            total_tool_calls=total_tool_calls,
        )


def _to_hook_message(message: Message) -> HookMessage:
    return HookMessage(
        role=Role(message.role).value,
        content=_text_of(message.content),
        tool_calls=[_to_hook_tool_call(call) for call in message.tool_calls or []],
        tool_call_id=message.tool_call_id,
    )


def _text_of(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        text = content
    else:
        text = "\n".join(part.text for part in content if isinstance(part, MessageContentTextPart))
    return text if text.strip() else ""


def _to_hook_tool_call(call: ToolCall) -> HookToolCall:
    return HookToolCall(
        id=call.id, name=call.function.name, arguments=_parse_arguments(call.function.arguments)
    )


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
