from abc import abstractmethod
from typing import Generic, TypeVar

from quickapp.config.tools.tool_fallback import BaseToolFallbackStrategyModel

T = TypeVar('T', bound=BaseToolFallbackStrategyModel)


class BaseStrategy(Generic[T]):
    @staticmethod
    @abstractmethod
    def handle(strategy_config: T, error: Exception) -> str: ...
