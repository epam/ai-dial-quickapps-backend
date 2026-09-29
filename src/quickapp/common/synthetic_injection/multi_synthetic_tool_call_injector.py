import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any

from aidial_sdk.chat_completion import Message, Role
from pydantic import BaseModel, ConfigDict

from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    BaseSyntheticInjector,
    BuiltSyntheticCall,
    build_synthetic_multi_call_turn,
    hash6,
)
from quickapp.common.tool_message_utils import after_first_user_idx


class SyntheticCall(BaseModel):
    """One tool call ``MultiSyntheticToolCallInjector`` should inject this turn.

    ``payload`` carries whatever a subclass needs at ``get_content`` time (e.g. the
    URL a call was built from), so it never has to recover that from the call's
    *index* in the list ``get_calls`` returned — index and list can drift apart the
    moment either side reorders or filters.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    tool_name: str
    arguments: dict[str, Any]
    payload: Any = None


class MultiSyntheticToolCallInjector(BaseSyntheticInjector, ABC):
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

    @abstractmethod
    async def get_calls(self, messages: list[Message]) -> list[SyntheticCall]:
        """Tool calls to inject this turn, in the order they should appear.
        Return ``[]`` to inject nothing."""
        ...

    @abstractmethod
    async def get_content(self, call: SyntheticCall, index: int, messages: list[Message]) -> str:
        """Tool result content for *call*, the entry at *index* in ``get_calls``'s
        list. Carry anything you need to build it on ``call.payload`` rather than
        recovering it from *index* — safer if the two lists ever diverge."""
        ...

    async def transform(self, messages: list[Message]) -> list[Message]:
        calls = await self.get_calls(messages)
        if not calls:
            return messages

        batch_prefix = self.__batch_prefix(calls)
        contents = await asyncio.gather(
            *(self.get_content(call, index, messages) for index, call in enumerate(calls))
        )
        built: list[BuiltSyntheticCall] = []
        for index, (call, content) in enumerate(zip(calls, contents)):
            # Format: {prefix}b_{signature_hash6}_i_{index}_c_{content_hash6}
            # Maximum length: prefix + 2+6+3+len(str(index))+3+6 chars.
            call_id = f"{batch_prefix}i_{index}_c_{hash6(content)}"
            state = self._enrich_state(call_id, content)
            built.append(
                BuiltSyntheticCall(
                    call_id=call_id,
                    tool_name=call.tool_name,
                    arguments=call.arguments,
                    content=content,
                    state=state,
                )
            )

        if (
            _find_assistant_with_ids(messages, [built_call.call_id for built_call in built])
            is not None
        ):
            return messages

        assistant_msg, tool_msgs = build_synthetic_multi_call_turn(built)
        idx = (
            len(messages)
            if _has_batch_occurrence(messages, batch_prefix)
            else after_first_user_idx(messages)
        )
        return messages[:idx] + [assistant_msg, *tool_msgs] + messages[idx:]

    def __batch_prefix(self, calls: list[SyntheticCall]) -> str:
        """Batch identity depends only on each call's tool name and arguments,
        independent of *payload* (arbitrary subclass data, not always JSON-safe)
        and of content, so a set from one turn never collides with a different set
        from another turn."""
        signature = json.dumps(
            [{"tool_name": call.tool_name, "arguments": call.arguments} for call in calls],
            sort_keys=True,
        )
        return f"{self.call_id_prefix}b_{hash6(signature)}_"


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
