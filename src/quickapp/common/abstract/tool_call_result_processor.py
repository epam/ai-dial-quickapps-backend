from abc import ABC, abstractmethod

from pydantic import BaseModel

from quickapp.common.tool_call_result import ToolCallResult


class ProcessingContext(BaseModel):
    tool_call_id: str | None
    tool_name: str
    size_threshold_override: int | None = None


class ToolCallResultProcessor(ABC):
    priority: int = 100

    @abstractmethod
    async def process(self, result: ToolCallResult, ctx: ProcessingContext) -> ToolCallResult: ...
