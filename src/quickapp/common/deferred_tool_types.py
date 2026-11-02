from typing import Annotated

from pydantic import BaseModel

from quickapp.config.tools.base import OpenAiToolConfigDict

DeferredToolName = Annotated[str, "DeferredToolName"]
DeferredToolCatalogEntry = Annotated[dict[str, str], "DeferredToolCatalogEntry"]
DeferredToolsetSummary = Annotated[dict[str, str | int | None], "DeferredToolsetSummary"]


class DeferredToolDefinition(BaseModel):
    name: str
    definition: OpenAiToolConfigDict
