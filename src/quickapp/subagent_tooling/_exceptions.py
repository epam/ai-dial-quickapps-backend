from quickapp.common.exceptions.tool_error import ToolErrorException


class SubagentToolErrorException(ToolErrorException):
    """Raised when a spawn fails to produce an answer the coordinator can use.

    A spoke that exhausts ``max_iterations`` mid-tool-loop, or that runs out its
    wall-clock budget, leaves no final assistant message behind. Returning that as an
    empty string would reach the coordinator's LLM as a *successful* tool result, and it
    would then answer from nothing. Raising routes the spawn through the ordinary
    tool-error path instead, where the coordinator can retry with a narrower task.
    """

    tool_kind = "Subagent"
