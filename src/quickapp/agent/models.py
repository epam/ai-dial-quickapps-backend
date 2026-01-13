from typing import Any

from aidial_sdk.chat_completion import Message, ToolCall
from aidial_sdk.utils.pydantic import ExtraAllowModel

TOOL_EXECUTION_HISTORY: str = 'tool_execution_history'


class ExecutedToolCallDTO(ExtraAllowModel):
    tool_call: ToolCall
    tool_execution_result: Message


OpenAiToolConfigDict = dict[str, Any]
