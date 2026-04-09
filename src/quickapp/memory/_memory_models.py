import datetime

from pydantic import BaseModel, Field

# Placeholder — extend with actual values from the memory service.
MemoryType = str


class MemoryRow(BaseModel):
    id: str
    memory_type: MemoryType
    content: str
    context: str
    importance: float
    embedding_model: str | None = None
    vector: list[float] | None = None
    timestamp: datetime.datetime
    access_count: int


class RetrieveResponse(BaseModel):
    facts: list[MemoryRow] = Field(default_factory=list)
