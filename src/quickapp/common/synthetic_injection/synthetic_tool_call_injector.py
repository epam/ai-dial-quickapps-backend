import hashlib
import json
import logging
import time
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

_DAILY_REFRESH_TTL_HOURS = 24
_DAILY_REFRESH_MARKER = "dr"


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
        frequency = await self.get_frequency(messages)

        match frequency:
            case InjectionFrequency.ALWAYS:
                content = await self.get_content(messages)
                if content is None:
                    return messages
                call_id = f"{self.call_id_prefix}{uuid4().hex[:12]}"
                idx = len(messages)
            case InjectionFrequency.APPEND_IF_CHANGED:
                content = await self.get_content(messages)
                if content is None:
                    return messages
                call_id, args_hash = _make_call_id(
                    self.call_id_prefix, tool_name, arguments, content
                )
                if _has_tool_call_id(messages, call_id):
                    return messages
                has_prior = _has_any_pair_for_tool_and_args(
                    messages, tool_name, args_hash, self.call_id_prefix
                )
                idx = len(messages) if has_prior else _after_first_user_idx(messages)
            case InjectionFrequency.DAILY_REFRESH:
                return await self._inject_daily_refresh(messages, tool_name, arguments)
            case _:
                logger.error("Unhandled frequency %r — skipping injection", frequency)
                return messages

        # Enrich the synthetic result so metadata matches real tool results.
        state = self._enrich_state(call_id, content)

        pair = _build_pair(tool_name, call_id, arguments, content, state)
        return messages[:idx] + list(pair) + messages[idx:]

    async def _inject_daily_refresh(
        self, messages: list[Message], tool_name: str, arguments: dict
    ) -> list[Message]:
        args_hash = _hash6(json.dumps(arguments, sort_keys=True))
        dr_prefix = f"{self.call_id_prefix}{tool_name}_{args_hash}_{_DAILY_REFRESH_MARKER}"
        existing = _find_daily_refresh_pair(messages, dr_prefix)

        if existing is None:
            content = await self.get_content(messages)
            if content is None:
                return messages
            call_id = _make_daily_refresh_call_id(dr_prefix, content)
            state = self._enrich_state(call_id, content)
            pair = _build_pair(tool_name, call_id, arguments, content, state)
            idx = _after_first_user_idx(messages)
            return messages[:idx] + list(pair) + messages[idx:]

        pair_idx, pair_call_id = existing
        if not _is_daily_refresh_stale(pair_call_id, dr_prefix):
            return messages

        content = await self.get_content(messages)
        if content is None:
            return messages

        new_call_id = _make_daily_refresh_call_id(dr_prefix, content)
        old_content = _get_tool_message_content(messages, pair_call_id)
        state = self._enrich_state(new_call_id, content)
        pair = _build_pair(tool_name, new_call_id, arguments, content, state)

        if content == old_content:
            # re-stamp in place — same content, refreshed epoch_hours in call_id
            return messages[:pair_idx] + list(pair) + messages[pair_idx + 2 :]
        else:
            # content changed — append at end
            return messages + list(pair)

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


def _make_daily_refresh_call_id(dr_prefix: str, content: str) -> str:
    """Build a DAILY_REFRESH call_id encoding current epoch_hours and content hash.

    Format: {dr_prefix}{epoch_hours:08x}_{content_hash6}
    """
    epoch_hours = int(time.time() / 3600)
    return f"{dr_prefix}{epoch_hours:08x}_{_hash6(content)}"


def _find_daily_refresh_pair(messages: list[Message], dr_prefix: str) -> tuple[int, str] | None:
    """Return (assistant_idx, call_id) of the first DAILY_REFRESH pair matching dr_prefix."""
    for i, m in enumerate(messages):
        if (
            m.role == Role.TOOL
            and m.tool_call_id is not None
            and m.tool_call_id.startswith(dr_prefix)
        ):
            return i - 1, m.tool_call_id
    return None


def _is_daily_refresh_stale(call_id: str, dr_prefix: str) -> bool:
    """Return True if the DAILY_REFRESH pair is older than _DAILY_REFRESH_TTL_HOURS."""
    epoch_str = call_id[len(dr_prefix) : len(dr_prefix) + 8]
    injection_epoch_hours = int(epoch_str, 16)
    return int(time.time() / 3600) - injection_epoch_hours >= _DAILY_REFRESH_TTL_HOURS


def _get_tool_message_content(messages: list[Message], call_id: str) -> str | None:
    """Return content of the TOOL message with the given tool_call_id."""
    for m in messages:
        if m.role == Role.TOOL and m.tool_call_id == call_id:
            content = m.content
            return content if isinstance(content, str) else None
    return None


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
