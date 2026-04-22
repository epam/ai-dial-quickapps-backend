from abc import ABC, abstractmethod

from quickapp.common.tool_call_result import ToolCallResult


class ToolCallResultEnricher(ABC):
    """Enriches a ToolCallResult after tool execution.

    Implementations are applied by ToolExecutor to every tool result.
    Enrichers should use "fill if absent" semantics — if the result
    already contains the metadata they would set, they should preserve it.
    """

    @abstractmethod
    def enrich(self, result: ToolCallResult) -> None: ...
