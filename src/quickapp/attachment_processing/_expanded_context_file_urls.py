"""Request-scoped file URLs discovered by expanding folder contexts."""

from pydantic import BaseModel, Field


class ExpandedContextFileUrls(BaseModel):
    """Populated when folder contexts are expanded for available-context."""

    urls: set[str] = Field(default_factory=set)
    populated: bool = False
