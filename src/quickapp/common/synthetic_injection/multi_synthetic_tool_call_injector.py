import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any

from aidial_sdk.chat_completion import Message, Role
from injector import ProviderOf

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.media_types import MediaTypes
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    build_synthetic_multi_call_turn,
    hash6,
)
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.common.tool_message_utils import after_first_user_idx


class MultiSyntheticToolCallInjector(MessagesTransformer, ABC):
    """Injects one synthetic assistant turn carrying several parallel tool calls and
    their results, generalizing ``SyntheticToolCallInjector``'s ``APPEND_IF_CHANGED``
    frequency to more than one call per turn.

    The whole set returned by ``get_calls`` is treated as one unit, identified by a
    signature built from every call's tool name and arguments (independent of
    content), so a set from one turn never collides with a different set from
    another turn:

    - The identical set with identical content already in the messages: no-op.
    - The same set found with different content (an earlier occurrence whose content
      has since changed): a fresh copy is appended at the end; the earlier occurrence
      is left where it is, mirroring how a single-call ``APPEND_IF_CHANGED`` injector
      behaves.
    - No occurrence at all: the new turn is inserted right after the first user
      message.
    """

    call_id_prefix: str = "synth_multi_"

    def __init__(
        self,
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]] | None = None,
    ) -> None:
        # Lazy: resolved at transform() time so this class can be constructed
        # during _RequestContextSetup, before ApplicationConfig is populated.
        self._enrichers_provider = enrichers_provider

    @abstractmethod
    async def get_calls(self, messages: list[Message]) -> list[tuple[str, dict]]:
        """Tool calls to inject this turn, as ``(tool_name, arguments)`` pairs, in
        the order they should appear. Return ``[]`` to inject nothing."""
        ...

    @abstractmethod
    async def get_content(
        self, tool_name: str, arguments: dict, index: int, messages: list[Message]
    ) -> str:
        """Tool result content for the call at *index* in ``get_calls``'s list."""
        ...

    async def transform(self, messages: list[Message]) -> list[Message]:
        calls = await self.get_calls(messages)
        if not calls:
            return messages

        batch_prefix = self.__batch_prefix(calls)
        contents = await asyncio.gather(
            *(
                self.get_content(tool_name, arguments, index, messages)
                for index, (tool_name, arguments) in enumerate(calls)
            )
        )
        built: list[tuple[str, str, dict, str, dict[str, Any] | None]] = []
        for index, ((tool_name, arguments), content) in enumerate(zip(calls, contents)):
            call_id = f"{batch_prefix}i_{index}_c_{hash6(content)}"
            state = self._enrich_state(call_id, content)
            built.append((call_id, tool_name, arguments, content, state))

        if _find_assistant_with_ids(messages, [call_id for call_id, *_ in built]) is not None:
            return messages

        assistant_msg, tool_msgs = build_synthetic_multi_call_turn(built)
        idx = (
            len(messages)
            if _has_batch_occurrence(messages, batch_prefix)
            else after_first_user_idx(messages)
        )
        return messages[:idx] + [assistant_msg, *tool_msgs] + messages[idx:]

    def __batch_prefix(self, calls: list[tuple[str, dict]]) -> str:
        signature = json.dumps(calls, sort_keys=False)
        return f"{self.call_id_prefix}b_{hash6(signature)}_"

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


def _find_assistant_with_ids(messages: list[Message], ids: list[str]) -> int | None:
    for i, m in enumerate(messages):
        if m.role == Role.ASSISTANT and m.tool_calls and [tc.id for tc in m.tool_calls] == ids:
            return i
    return None


def _has_batch_occurrence(messages: list[Message], batch_prefix: str) -> bool:
    return any(
        m.role == Role.ASSISTANT
        and m.tool_calls
        and all(tc.id.startswith(batch_prefix) for tc in m.tool_calls)
        for m in messages
    )
