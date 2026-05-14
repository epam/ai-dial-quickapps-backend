from abc import ABC, abstractmethod


class ToolExecutionHistoryPolicy(ABC):
    """Post-processes tool_execution_history before it is persisted to choice state.

    Each feature module owns a policy for its own tool messages. Policies run in
    order on a terminal completion (no exception, no pending tool calls); they
    must operate on a mutable history list and return the (possibly modified)
    same list.
    """

    @abstractmethod
    def apply(self, history: list[dict[str, object]]) -> list[dict[str, object]]: ...
