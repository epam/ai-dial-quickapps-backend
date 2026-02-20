from abc import ABC, abstractmethod

from quickapp.common.completion_result import CompletionResult


class CompletionResultEnricher(ABC):
    @abstractmethod
    def enrich(self, result: CompletionResult) -> None: ...
