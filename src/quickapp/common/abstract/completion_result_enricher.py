from abc import ABC, abstractmethod

from quickapp.common.completion_result import CompletionResult


class CompletionResultEnricher(ABC):
    """Enriches a CompletionResult after tool execution.

    Implementations are applied by ToolExecutor to every tool result.
    Enrichers should use "fill if absent" semantics — if the result
    already contains the metadata they would set, they should preserve it.
    """

    @abstractmethod
    def enrich(self, result: CompletionResult) -> None: ...
