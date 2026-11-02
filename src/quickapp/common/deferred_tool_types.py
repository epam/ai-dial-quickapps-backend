from typing import Annotated, TypedDict

from pydantic import BaseModel

from quickapp.config.tools.base import OpenAiToolConfigDict

DeferredToolName = Annotated[str, "DeferredToolName"]


class DeferredToolCatalogEntry(TypedDict):
    """`toolset` is the localized toolset display name — the join key of the hierarchy strategy."""

    name: str
    description: str
    toolset: str


DeferredToolsetSummary = Annotated[dict[str, str | int | None], "DeferredToolsetSummary"]


class DeferredToolDefinition(BaseModel):
    name: str
    definition: OpenAiToolConfigDict
