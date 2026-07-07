from aidial_sdk.chat_completion.request import ToolChoice
from injector import inject

from quickapp.common import TOOL_CHOICE


@inject
class _ToolChoiceHolder:
    """Request-scoped holder that returns tool_choice on the first consume() call."""

    def __init__(self, tool_choice: TOOL_CHOICE) -> None:
        self._value: ToolChoice | str | None = tool_choice
        self._consumed: bool = False

    def consume(self) -> ToolChoice | str | None:
        """Consume tool_choice on the first consume() call."""
        if self._consumed:
            return None  # tool_choice applies only to the first LLM call
        self._consumed = True
        return self._value
