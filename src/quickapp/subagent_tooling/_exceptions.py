from quickapp.common.exceptions.tool_error import ToolErrorException


class SubagentToolErrorException(ToolErrorException):
    """Raised when a spawn fails to produce an answer the coordinator can use.

    A spoke that exhausts ``max_iterations`` mid-tool-loop leaves no final assistant
    message behind. Returning that as an empty string would reach the coordinator's LLM
    as a *successful* tool result, and it would then answer from nothing — the same
    confabulation failure ``SubagentToolSetResolutionError`` exists to prevent. Raising
    routes the spawn through the ordinary tool-error path instead.
    """

    tool_kind = "Subagent"


class SubagentToolSetResolutionError(RuntimeError):
    """Raised when a subagent's declared tool sets resolve to nothing.

    Spawning anyway would run an agent with no tools, which does not fail — it
    answers from the task text alone and sounds confident doing it. That is worse
    than an error, so this is fatal to the spawn.
    """

    def __init__(self, subagent_name: str, requested: list[str], available: list[str]) -> None:
        super().__init__(
            f"Subagent '{subagent_name}' declares tool sets {requested}, none of which exist "
            f"in this app. Available tool sets: {available or '(none)'}."
        )
        self.subagent_name = subagent_name
        self.requested = requested
        self.available = available
