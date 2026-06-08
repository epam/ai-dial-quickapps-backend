from abc import ABC, abstractmethod

from quickapp.common.tool_call_result import ToolCallResult


class ToolCallResultEnricher(ABC):
    """Enriches a ToolCallResult after it is produced.

    Implementations are applied to every tool result — both real ones
    returned by ``ToolExecutor`` and synthetic ones produced by
    ``SyntheticToolCallInjector`` subclasses. Enrichers should use
    "fill if absent" semantics — if the result already contains the
    metadata they would set, they should preserve it.
    """

    @abstractmethod
    def enrich(self, result: ToolCallResult) -> None: ...
