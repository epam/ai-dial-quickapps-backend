from abc import ABC, abstractmethod

from pydantic import BaseModel

from quickapp.common.tool_call_result import ToolCallResult


class ProcessingContext(BaseModel):
    tool_call_id: str | None
    tool_name: str


class ToolCallResultProcessor(ABC):
    # Lower values run earlier; ties broken by registration order (stable sort).
    # Default 0 means "no preference" and may be negative. Mirrors BaseInitializer.order.
    order: int = 0

    @abstractmethod
    async def process(self, result: ToolCallResult, ctx: ProcessingContext) -> ToolCallResult: ...
