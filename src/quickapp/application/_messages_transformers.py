import copy
import logging
import warnings

from aidial_sdk.chat_completion import Message, Role
from injector import inject, ProviderOf
from pydantic import StrictStr

from quickapp.agent.agent_instructions_provider import AgentInstructionsProvider
from quickapp.agent.models import TOOL_EXECUTION_HISTORY, ExecutedToolCallDTO
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.config.application import ApplicationConfig

logger = logging.getLogger(__name__)


class AddSystemPromptTransformer(MessagesTransformer):
    @inject
    def __init__(
        self,
        config_provider: ProviderOf[ApplicationConfig],
        instructions_provider: AgentInstructionsProvider,
    ):
        self.__config_provider = config_provider
        self.__instructions_provider = instructions_provider

    def transform(self, messages: list[Message]) -> list[Message]:
        parts = (self.__config_provider.get().orchestrator.system_prompt.content or "", self.__instructions_provider.get() or "")
        combined_system_prompt = "\n\n".join(p for p in parts if p)

        if not isinstance(messages, list):
            raise TypeError("Data must be a list of Message objects")
        if not combined_system_prompt:
            return messages
        if len(messages) > 0 and messages[0].role != Role.SYSTEM:
            return [Message(role=Role.SYSTEM, content=StrictStr(combined_system_prompt))] + messages

        return messages


class ExtractToolCallsFromStateProcessor(MessagesTransformer):
    """Extracts tool execution history from state and inserts as messages.

    Supports two formats:
    - New format (message-based): List of serialized Message objects
    - Legacy format (deprecated): List of ExecutedToolCallDTO objects
    """

    @staticmethod
    def _is_legacy_format(tool_history: list) -> bool:
        """Check if the history is in the legacy ExecutedToolCallDTO format.

        Legacy format has "tool_call" key at root level.
        New format has "role" key (Message objects).
        """
        if not tool_history:
            return False
        return "tool_call" in tool_history[0]

    @staticmethod
    def _extract_legacy_format(tool_history: list, assistant_message: Message) -> list[Message]:
        """Extract messages from legacy ExecutedToolCallDTO format.

        DEPRECATED: This format is deprecated and will be removed in a future version.
        Use message-based format instead.
        """
        warnings.warn(
            "Legacy tool_execution_history format (ExecutedToolCallDTO) is deprecated. "
            "This will be removed in a future version.",
            DeprecationWarning,
            stacklevel=3,
        )

        extracted_messages: list[Message] = []
        for history_part in tool_history:
            executed_tool_call = ExecutedToolCallDTO.validate(history_part)
            assistant_tool_call = copy.deepcopy(assistant_message)
            assistant_tool_call.content = StrictStr("")

            if assistant_tool_call.tool_calls is None:
                assistant_tool_call.tool_calls = []
            assistant_tool_call.tool_calls.append(executed_tool_call.tool_call)

            extracted_messages.append(assistant_tool_call)
            extracted_messages.append(executed_tool_call.tool_execution_result)

        return extracted_messages

    @staticmethod
    def _extract_message_format(tool_history: list) -> list[Message]:
        """Extract messages from message-based format (new format)."""
        return [Message(**msg_dict) for msg_dict in tool_history]

    def transform(self, messages: list[Message]) -> list[Message]:
        """Unpack tool execution history from state into message sequence.

        Expands ASSISTANT messages with tool_execution_history state into
        the full sequence of ASSISTANT and TOOL messages.
        """
        updated_messages: list[Message] = []

        for message in messages:
            custom_content = message.custom_content
            if (
                message.role == Role.ASSISTANT
                and custom_content
                and custom_content.state
                and (tool_history := custom_content.state.get(TOOL_EXECUTION_HISTORY)) is not None
            ):
                # Prepare the final assistant message (without tool_execution_history)
                assistant_message = copy.deepcopy(message)
                if assistant_message.custom_content and assistant_message.custom_content.state:
                    assistant_message.custom_content.state.pop(TOOL_EXECUTION_HISTORY, None)

                # Extract messages based on format
                if self._is_legacy_format(tool_history):
                    extracted = self._extract_legacy_format(tool_history, assistant_message)
                else:
                    extracted = self._extract_message_format(tool_history)

                updated_messages.extend(extracted)
                updated_messages.append(assistant_message)
            else:
                updated_messages.append(message)

        return updated_messages
