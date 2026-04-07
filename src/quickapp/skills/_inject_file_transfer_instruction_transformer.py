import json
import logging

from aidial_sdk.chat_completion import FunctionCall, Message, Role, ToolCall
from injector import inject

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.skills._tool_configs import SKILL_READER_TOOL_NAME
from quickapp.skills.agent_skills_provider import AgentSkillsProvider

logger = logging.getLogger(__name__)

# Skills to inject at conversation start: skill_name -> synthetic tool call ID.
# IDs are stable so existing conversation history is not affected on redeploy.
BUILTIN_SKILLS_TO_INJECT: dict[str, str] = {
    "tool-call-file-parameter-formatting": "call_synthetic_file_transfer_0001",
    "dial-memory": "call_synthetic_dial_memory_0001",
}


class _InjectFileTransferInstructionTransformer(MessagesTransformer):
    """
    Injects synthetic tool calls to read builtin skills at the beginning of
    the conversation (one tool call per skill, injected only once).
    """

    @inject
    def __init__(self, skills_provider: AgentSkillsProvider):
        self.__skills_provider = skills_provider

    def transform(self, messages: list[Message]) -> list[Message]:
        synthetic_messages: list[Message] = []

        for skill_name, tool_call_id in BUILTIN_SKILLS_TO_INJECT.items():
            if self._is_skill_injected(messages, tool_call_id):
                logger.debug("Synthetic tool call for '%s' already present, skipping", skill_name)
                continue

            try:
                skill_content = self.__skills_provider.get_skill_content(skill_name)
            except (FileNotFoundError, ValueError) as e:
                logger.error("Builtin skill '%s' not found, skipping injection: %s", skill_name, e)
                continue

            synthetic_messages.extend(self._create_synthetic_tool_call(skill_name, tool_call_id, skill_content))

        if not synthetic_messages:
            return messages

        if messages and messages[0].role == Role.SYSTEM:
            return [messages[0]] + synthetic_messages + messages[1:]
        return synthetic_messages + messages

    @staticmethod
    def _is_skill_injected(messages: list[Message], tool_call_id: str) -> bool:
        return any(m.role == Role.TOOL and m.tool_call_id == tool_call_id for m in messages)

    @staticmethod
    def _create_synthetic_tool_call(skill_name: str, tool_call_id: str, skill_content: str) -> list[Message]:
        tool_call = ToolCall(
            id=tool_call_id,
            type="function",
            function=FunctionCall(
                name=SKILL_READER_TOOL_NAME,
                arguments=json.dumps({"skill_name": skill_name}),
            ),
        )

        assistant_message = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[tool_call],
        )

        tool_response = Message(
            role=Role.TOOL,
            tool_call_id=tool_call_id,
            content=skill_content,
        )

        return [assistant_message, tool_response]
