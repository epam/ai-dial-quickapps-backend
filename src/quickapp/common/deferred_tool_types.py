from typing import Annotated, TypedDict

from pydantic import BaseModel

from quickapp.config.tools.base import OpenAiToolConfigDict

DeferredToolName = Annotated[str, "DeferredToolName"]


class DeferredToolCatalogEntry(TypedDict):
    """`toolset` is the localized display name of the toolset the tool belongs to."""

    name: str
    description: str
    toolset: str


class DeferredToolsetSummary(TypedDict):
    name: str
    description: str | None
    tool_count: int


class DeferredToolDefinition(BaseModel):
    name: str
    definition: OpenAiToolConfigDict
