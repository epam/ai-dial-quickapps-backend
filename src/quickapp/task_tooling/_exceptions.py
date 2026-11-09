from quickapp.common.exceptions.tool_error import ToolErrorException
from quickapp.common.tool_names import INTERNAL_RUN_TASK_TOOL_NAME


class TaskToolErrorException(ToolErrorException):
    """Raised when a task ends without an answer the delegating agent can use.

    A task that exhausts its iteration or time budget leaves no final message.
    Returning "" would reach the LLM as a *successful* empty result and it would
    answer from nothing; an error tells it why, so it can retry with a narrower task.
    """

    tool_kind = "Task"

    def __init__(self, error_message: str):
        super().__init__(INTERNAL_RUN_TASK_TOOL_NAME, error_message)
