import json
import logging
from abc import ABC, abstractmethod
from uuid import uuid4

from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.chat_completion.request import FunctionCall, ToolCall

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.synthetic_injection._injection_enums import (
    InjectionFrequency,
    InjectionPosition,
)

logger = logging.getLogger(__name__)


class SyntheticToolCallInjector(MessagesTransformer, ABC):
    position: InjectionPosition
    frequency: InjectionFrequency
    call_id_prefix: str = "synthetic_"

    @abstractmethod
    async def get_tool_name(self) -> str: ...

    async def get_arguments(self) -> dict:
        return {}

    @abstractmethod
    async def get_content(self, messages: list[Message]) -> str | None:
        """Return the tool result content string, or None to skip injection."""
        ...

    def condition(self, messages: list[Message]) -> bool:
        """Override when frequency == CONDITIONAL."""
        return True

    async def transform(self, messages: list[Message]) -> list[Message]:
        tool_name = await self.get_tool_name()
        call_id: str

        # 1. Frequency gate
        match self.frequency:
            case InjectionFrequency.ONCE:
                call_id = f"synthetic_once_{tool_name}"
                if _has_tool_call_id(messages, call_id):
                    return messages
            case InjectionFrequency.REFRESH:
                call_id = f"synthetic_once_{tool_name}"
                messages = _remove_pair_by_call_id(messages, call_id)
            case InjectionFrequency.CONDITIONAL:
                if not self.condition(messages):
                    return messages
                call_id = f"{self.call_id_prefix}{uuid4().hex[:12]}"
            case InjectionFrequency.ALWAYS:
                call_id = f"{self.call_id_prefix}{uuid4().hex[:12]}"

        # 2. Content fetch
        content = await self.get_content(messages)
        if content is None:
            return messages

        # 3. Pair construction
        arguments = await self.get_arguments()
        pair = _build_pair(tool_name, call_id, arguments, content)

        # 4. Position splice
        match self.position:
            case InjectionPosition.AFTER_FIRST_USER:
                idx = next(
                    (i + 1 for i, m in enumerate(messages) if m.role == Role.USER),
                    len(messages),
                )
            case InjectionPosition.BEFORE_LAST_USER:
                idx = next(
                    (i for i in range(len(messages) - 1, -1, -1) if messages[i].role == Role.USER),
                    len(messages),
                )
            case InjectionPosition.END:
                idx = len(messages)

        return messages[:idx] + list(pair) + messages[idx:]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_tool_call_id(messages: list[Message], call_id: str) -> bool:
    return any(m.role == Role.TOOL and m.tool_call_id == call_id for m in messages)


def _remove_pair_by_call_id(messages: list[Message], call_id: str) -> list[Message]:
    """Remove the ASSISTANT+TOOL pair that has the given call_id."""
    result: list[Message] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if (
            msg.role == Role.ASSISTANT
            and msg.tool_calls
            and any(tc.id == call_id for tc in msg.tool_calls)
        ):
            # Skip this ASSISTANT message and the immediately following TOOL message(s) with this call_id
            i += 1
            while (
                i < len(messages)
                and messages[i].role == Role.TOOL
                and messages[i].tool_call_id == call_id
            ):
                i += 1
            continue
        result.append(msg)
        i += 1
    return result


def _build_pair(
    tool_name: str, call_id: str, arguments: dict, content: str
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
    )
    return assistant_msg, tool_msg
