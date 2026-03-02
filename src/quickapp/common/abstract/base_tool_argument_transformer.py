from abc import ABC, abstractmethod
from typing import Any


class ToolArgumentTransformer(ABC):
    """Transforms tool call arguments before execution.

    Implementations are applied to all tool types via the StagedBaseTool chain.
    """

    @abstractmethod
    async def transform(self, kwargs: dict[str, Any]) -> dict[str, Any]: ...
