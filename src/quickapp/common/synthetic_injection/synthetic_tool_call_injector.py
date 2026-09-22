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
from quickapp.common.tool_message_utils import after_first_user_idx

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

    def _make_call_id_prefix(self, tool_name: str, arguments: dict) -> str:
        """Return the stable prefix for a tool+args pair (no content, no TTL)."""
        tool_hash = _hash6(tool_name)
        args_hash = _hash6(json.dumps(arguments, sort_keys=True))
        return f"{self.call_id_prefix}t_{tool_hash}_a_{args_hash}_"

    def make_call_id(
        self,
        tool_name: str,
        arguments: dict,
        content: str,
        ttl_expiry_seconds: int | None = None,
    ) -> str:
        """Build a structured call_id for the given tool+args+content.

        Format: {prefix}t_{tool_hash6}_a_{args_hash6}_c_{content_hash6}[_ttl_{expiry:08x}]
        Maximum length: prefix + 2+6+3+6+3+6+5+8 = prefix + 39 chars (≤ 64 for any prefix ≤ 25).
        """
        tool_hash = _hash6(tool_name)
        args_hash = _hash6(json.dumps(arguments, sort_keys=True))
        content_hash = _hash6(content)
        base = f"{self.call_id_prefix}t_{tool_hash}_a_{args_hash}_c_{content_hash}"
        if ttl_expiry_seconds is not None:
            return f"{base}_ttl_{ttl_expiry_seconds:08x}"
        return base

    @staticmethod
    def _parse_call_id_ttl_expiry(call_id: str) -> int | None:
        """Extract TTL expiry seconds from a call_id, or None if not present."""
        marker = "_ttl_"
        idx = call_id.rfind(marker)
        if idx == -1:
            return None
        hex_str = call_id[idx + len(marker) :]
        try:
            return int(hex_str, 16)
        except ValueError:
            return None

    async def transform(self, messages: list[Message]) -> list[Message]:
        if not await self.should_inject(messages):
            return messages

        tool_name = await self.get_tool_name()
        arguments = await self.get_arguments()
        frequency = await self.get_frequency(messages)

        match frequency:
            case InjectionFrequency.ALWAYS:
                return await self._inject_always(messages, tool_name, arguments)
            case InjectionFrequency.APPEND_IF_CHANGED:
                return await self._inject_append_if_changed(messages, tool_name, arguments)

    async def _inject_always(
        self, messages: list[Message], tool_name: str, arguments: dict
    ) -> list[Message]:
        content = await self.get_content(messages)
        if content is None:
            return messages
        call_id = self.make_call_id(tool_name, arguments, uuid4().hex[:12])
        return self._inject_at(messages, len(messages), tool_name, call_id, arguments, content)

    async def _inject_append_if_changed(
        self, messages: list[Message], tool_name: str, arguments: dict
    ) -> list[Message]:
        content = await self.get_content(messages)
        if content is None:
            return messages

        call_id = self.make_call_id(tool_name, arguments, content)
        args_prefix = self._make_call_id_prefix(tool_name, arguments)
        # Prefix matching same tool+args+content, ignoring any _ttl_ suffix
        ac_prefix = args_prefix + f"c_{_hash6(content)}"

        pair = _find_pair_with_args_and_content(messages, ac_prefix)
        if pair is not None:
            pair_idx, _ = pair
            # Replace in place (re-stamps TTL when expiry changed, no-op when identical)
            state = self._enrich_state(call_id, content)
            new_pair = _build_pair(tool_name, call_id, arguments, content, state)
            return messages[:pair_idx] + list(new_pair) + messages[pair_idx + 2 :]

        has_prior_args = _has_any_pair_with_prefix(messages, args_prefix)
        idx = len(messages) if has_prior_args else after_first_user_idx(messages)
        return self._inject_at(messages, idx, tool_name, call_id, arguments, content)

    def _inject_at(
        self,
        messages: list[Message],
        idx: int,
        tool_name: str,
        call_id: str,
        arguments: dict,
        content: str,
    ) -> list[Message]:
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


def _has_any_pair_with_prefix(messages: list[Message], id_prefix: str) -> bool:
    return any(
        m.role == Role.TOOL and m.tool_call_id is not None and m.tool_call_id.startswith(id_prefix)
        for m in messages
    )


def _find_pair_with_args_and_content(
    messages: list[Message], ac_prefix: str
) -> tuple[int, str] | None:
    """Return (assistant_idx, call_id) for the first TOOL message whose call_id starts with ac_prefix."""
    for i, m in enumerate(messages):
        if (
            m.role == Role.TOOL
            and m.tool_call_id is not None
            and m.tool_call_id.startswith(ac_prefix)
        ):
            return i - 1, m.tool_call_id
    return None


def _build_pair(
    tool_name: str,
    call_id: str,
    arguments: dict,
    content: str,
    state: dict[str, Any] | None = None,
) -> tuple[Message, Message]:
    assistant_msg, tool_msgs = build_synthetic_multi_call_turn(
        [(call_id, tool_name, arguments, content, state)]
    )
    return assistant_msg, tool_msgs[0]


def build_synthetic_multi_call_turn(
    calls: list[tuple[str, str, dict, str, dict[str, Any] | None]],
) -> tuple[Message, list[Message]]:
    """One assistant message carrying every call as a parallel ``tool_calls`` entry,
    followed by one tool result message per call — the same shape a model-initiated
    parallel tool call turn has.

    ``calls`` is ``(call_id, tool_name, arguments, content, state)`` tuples, in the
    order the calls should appear.
    """
    assistant_msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                id=call_id,
                type="function",
                function=FunctionCall(name=tool_name, arguments=json.dumps(arguments)),
            )
            for call_id, tool_name, arguments, _content, _state in calls
        ],
    )
    tool_msgs = [
        Message(
            role=Role.TOOL,
            content=content,
            tool_call_id=call_id,
            custom_content=CustomContent(state=state) if state else None,
        )
        for call_id, _tool_name, _arguments, content, state in calls
    ]
    return assistant_msg, tool_msgs


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
        built: list[tuple[str, str, dict, str, dict[str, Any] | None]] = []
        for index, (tool_name, arguments) in enumerate(calls):
            content = await self.get_content(tool_name, arguments, index, messages)
            call_id = f"{batch_prefix}i_{index}_c_{_hash6(content)}"
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
        return f"{self.call_id_prefix}b_{_hash6(signature)}_"

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
