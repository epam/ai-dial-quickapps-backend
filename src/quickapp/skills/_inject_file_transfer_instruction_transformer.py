import json
import logging

from aidial_sdk.chat_completion import FunctionCall, Message, Role, ToolCall
from injector import inject

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.skills._tool_configs import SKILL_READER_TOOL_NAME
from quickapp.skills.agent_skills_provider import AgentSkillsProvider

logger = logging.getLogger(__name__)

# The skill name to inject (file transfer formatting instructions)
BUILTIN_FILE_TRANSFER_SKILL = "tool-call-file-parameter-formatting"
SYNTHETIC_TOOL_CALL_ID = "call_synthetic_file_transfer_0001"


class _InjectFileTransferInstructionTransformer(MessagesTransformer):
    """
    Injects a synthetic tool call to read the builtin_file_transfer skill
    at the beginning of the conversation (only once).

    This ensures the agent learns about file parameter formatting rules
    before processing any user requests.
    """

    @inject
    def __init__(self, skills_provider: AgentSkillsProvider):
        self.__skills_provider = skills_provider

    def transform(self, messages: list[Message]) -> list[Message]:
        # Check if synthetic tool call already exists in history
        if self._has_synthetic_tool_call(messages):
            logger.debug("Synthetic file transfer instruction already present, skipping injection")
            return messages

        # Check if the skill exists
        try:
            skill_content = self.__skills_provider.get_skill_content(BUILTIN_FILE_TRANSFER_SKILL)
        except (FileNotFoundError, ValueError) as e:
            logger.error(f"Builtin file transfer skill not found, skipping injection: {e}")
            return messages

        # Create synthetic tool call and response
        synthetic_messages = self._create_synthetic_tool_call(skill_content)

        # Inject after the first user message to satisfy model constraints
        # (e.g. Gemini requires tool calls after a user turn, not after system)
        first_user_idx = next(
            (i for i, m in enumerate(messages) if m.role == Role.USER),
            None,
        )

        if first_user_idx is not None:
            insert_pos = first_user_idx + 1
            result = messages[:insert_pos] + synthetic_messages + messages[insert_pos:]
        else:
            # No user message (edge case) — append at the end
            result = messages + synthetic_messages

        logger.debug("Injected synthetic file transfer instruction tool call")
        return result

    @staticmethod
    def _has_synthetic_tool_call(messages: list[Message]) -> bool:
        """Check if synthetic tool call already exists in message history."""
        for message in messages:
            if message.role == Role.TOOL and message.tool_call_id == SYNTHETIC_TOOL_CALL_ID:
                return True
        return False

    @staticmethod
    def _create_synthetic_tool_call(skill_content: str) -> list[Message]:
        """Create synthetic assistant message with tool call and tool response."""
        # Create the tool call
        tool_call = ToolCall(
            id=SYNTHETIC_TOOL_CALL_ID,
            type="function",
            function=FunctionCall(
                name=SKILL_READER_TOOL_NAME,
                arguments=json.dumps({"skill_name": BUILTIN_FILE_TRANSFER_SKILL}),
            ),
        )

        # Assistant message with tool call
        assistant_message = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[tool_call],
        )

        # Tool response message
        tool_response = Message(
            role=Role.TOOL,
            tool_call_id=SYNTHETIC_TOOL_CALL_ID,
            content=skill_content,
        )

        return [assistant_message, tool_response]
