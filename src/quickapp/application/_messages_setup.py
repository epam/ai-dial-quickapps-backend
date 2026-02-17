import copy
import logging
import warnings

from aidial_sdk.chat_completion import Message, Role, ToolCall
from aidial_sdk.utils.pydantic import ExtraAllowModel
from injector import inject
from pydantic import StrictStr

from quickapp.agent.models import TOOL_EXECUTION_HISTORY
from quickapp.common.abstract.base_transformer import MessagesTransformer

logger = logging.getLogger(__name__)


class ExecutedToolCallDTO(ExtraAllowModel):
    tool_call: ToolCall
    tool_execution_result: Message


@inject
class _MessagesSetup:

    def __init__(
        self,
        transformers: list[MessagesTransformer],
    ):
        self.__transformers = transformers
        logger.debug(f"Messages transformers: {transformers}")

    def setup(self, messages: list[Message]) -> list[Message]:
        messages = self.extract_tool_calls(messages)
        for transformer in self.__transformers:
            messages = transformer.transform(messages)
        return messages

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

    def extract_tool_calls(self, messages: list[Message]) -> list[Message]:
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
