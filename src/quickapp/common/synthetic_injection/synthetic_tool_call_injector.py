import hashlib
import json
import logging
from abc import ABC, abstractmethod
from typing import Any
from uuid import uuid4

from aidial_sdk.chat_completion import CustomContent, Message, Role
from aidial_sdk.chat_completion.request import FunctionCall, ToolCall
from injector import ProviderOf

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.media_types import MediaTypes
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.common.tool_call_result import ToolCallResult

logger = logging.getLogger(__name__)


class SyntheticToolCallInjector(MessagesTransformer, ABC):
    call_id_prefix: str = "synth_"

    def __init__(
        self,
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]] | None = None,
    ) -> None:
        # Lazy: resolved at transform() time so this class can be constructed
        # during _RequestContextSetup, before ApplicationConfig is populated.
        self._enrichers_provider = enrichers_provider

    @abstractmethod
    async def get_tool_name(self) -> str: ...

    @abstractmethod
    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency: ...

    async def get_arguments(self) -> dict:
        return {}

    async def should_inject(self, messages: list[Message]) -> bool:
        """Return False to skip injection entirely. Override to add preconditions."""
        return True

    @abstractmethod
    async def get_content(self, messages: list[Message]) -> str | None:
        """Return the tool result content string, or None to skip injection."""
        ...

    async def transform(self, messages: list[Message]) -> list[Message]:
        if not await self.should_inject(messages):
            return messages

        tool_name = await self.get_tool_name()
        arguments = await self.get_arguments()

        content = await self.get_content(messages)
        if content is None:
            return messages

        frequency = await self.get_frequency(messages)

        match frequency:
            case InjectionFrequency.ALWAYS:
                call_id = f"{self.call_id_prefix}{uuid4().hex[:12]}"
                idx = len(messages)
            case InjectionFrequency.APPEND_IF_CHANGED:
                call_id, args_hash = _make_call_id(
                    self.call_id_prefix, tool_name, arguments, content
                )
                if _has_tool_call_id(messages, call_id):
                    return messages
                has_prior = _has_any_pair_for_tool_and_args(
                    messages, tool_name, args_hash, self.call_id_prefix
                )
                idx = len(messages) if has_prior else _after_first_user_idx(messages)

        # Enrich the synthetic result so metadata matches real tool results.
        state = self._enrich_state(call_id, content)

        pair = _build_pair(tool_name, call_id, arguments, content, state)
        return messages[:idx] + list(pair) + messages[idx:]

    def _enrich_state(self, call_id: str, content: str) -> dict[str, Any] | None:
        if self._enrichers_provider is None:
            return None
        enrichers = self._enrichers_provider.get()
        if not enrichers:
            return None
        transient = ToolCallResult(
            tool_call_id=call_id,
            content=content,
            content_type=MediaTypes.PLAIN_TEXT,
        )
        for enricher in enrichers:
            enricher.enrich(transient)
        return transient.state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash6(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:6]


def _make_call_id(
    call_id_prefix: str, tool_name: str, arguments: dict, content: str
) -> tuple[str, str]:
    """Return (call_id, args_hash) for content-addressed injection frequencies."""
    args_hash = _hash6(json.dumps(arguments, sort_keys=True))
    call_id = f"{call_id_prefix}{tool_name}_{args_hash}_{_hash6(content)}"
    return call_id, args_hash


def _after_first_user_idx(messages: list[Message]) -> int:
    return next(
        (i + 1 for i, m in enumerate(messages) if m.role == Role.USER),
        len(messages),
    )


def _has_tool_call_id(messages: list[Message], call_id: str) -> bool:
    return any(m.role == Role.TOOL and m.tool_call_id == call_id for m in messages)


def _has_any_pair_for_tool_and_args(
    messages: list[Message], tool_name: str, args_hash: str, call_id_prefix: str
) -> bool:
    id_prefix = f"{call_id_prefix}{tool_name}_{args_hash}_"
    return any(
        m.role == Role.TOOL and m.tool_call_id is not None and m.tool_call_id.startswith(id_prefix)
        for m in messages
    )


def _build_pair(
    tool_name: str,
    call_id: str,
    arguments: dict,
    content: str,
    state: dict[str, Any] | None = None,
) -> tuple[Message, Message]:
    assistant_msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                id=call_id,
                type="function",
                function=FunctionCall(
                    name=tool_name,
                    arguments=json.dumps(arguments),
                ),
            )
        ],
    )
    tool_msg = Message(
        role=Role.TOOL,
        content=content,
        tool_call_id=call_id,
        custom_content=CustomContent(state=state) if state else None,
    )
    return assistant_msg, tool_msg
