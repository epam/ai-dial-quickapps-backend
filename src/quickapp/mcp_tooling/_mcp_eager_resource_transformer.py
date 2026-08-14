import json
import logging
from uuid import uuid4

from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.chat_completion.request import FunctionCall, ToolCall
from injector import inject

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.tool_message_utils import after_first_user_idx
from quickapp.common.tool_names import INTERNAL_MCP_READ_RESOURCE_TOOL_NAME
from quickapp.mcp_tooling._mcp_tooling_context import _MCPToolingContext

logger = logging.getLogger(__name__)


def _build_synthetic_pair(uri: str, toolset_name: str, text: str) -> tuple[Message, Message]:
    """Build the (assistant tool-call, tool result) pair for an eager resource."""
    call_id = f"synth_mcp_res_{uuid4().hex[:12]}"
    assistant_msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                id=call_id,
                type="function",
                function=FunctionCall(
                    name=INTERNAL_MCP_READ_RESOURCE_TOOL_NAME,
                    arguments=json.dumps({"uri": uri, "toolset": toolset_name}),
                ),
            )
        ],
    )
    tool_msg = Message(
        role=Role.TOOL,
        content=text,
        tool_call_id=call_id,
    )
    return assistant_msg, tool_msg


def _already_injected_pairs(messages: list[Message]) -> set[tuple[str, str]]:
    """Return the set of (uri, toolset_name) pairs already present in message history.

    Scans Role.ASSISTANT messages for ToolCall.function.name == 'read_mcp_resource'
    and extracts uri + toolset from the call arguments.
    """
    seen: set[tuple[str, str]] = set()
    for msg in messages:
        if msg.role != Role.ASSISTANT:
            continue
        for tc in msg.tool_calls or []:
            if tc.function.name != INTERNAL_MCP_READ_RESOURCE_TOOL_NAME:
                continue
            try:
                args = json.loads(tc.function.arguments or "{}")
                uri = args.get("uri", "")
                toolset = args.get("toolset", "")
                if uri:
                    seen.add((uri, toolset))
            except (json.JSONDecodeError, AttributeError):
                pass
    return seen


@inject
class _MCPEagerResourceTransformer(MessagesTransformer):
    """Prepends synthetic read_mcp_resource tool call pairs for eager resources.

    Runs once per request setup (MessagesTransformer contract). Skips pairs already
    present in message history so multi-turn conversations don't re-inject on turn 2+.
    When items is None no eager resources exist and this transformer is always a no-op.
    """

    def __init__(self, context: _MCPToolingContext) -> None:
        self._context = context

    async def transform(self, messages: list[Message]) -> list[Message]:
        eager = self._context.eager_resources
        if not eager:
            return messages

        already_seen = _already_injected_pairs(messages)
        insert_idx = after_first_user_idx(messages)

        new_pairs: list[tuple[Message, Message]] = []
        for resource in eager:
            key = (resource.resource_uri, resource.toolset_name)
            if key in already_seen:
                continue
            already_seen.add(key)
            new_pairs.append(
                _build_synthetic_pair(
                    uri=resource.resource_uri,
                    toolset_name=resource.toolset_name,
                    text=resource.text,
                )
            )

        if not new_pairs:
            return messages

        flattened: list[Message] = []
        for assistant_msg, tool_msg in new_pairs:
            flattened.append(assistant_msg)
            flattened.append(tool_msg)

        return messages[:insert_idx] + flattened + messages[insert_idx:]
