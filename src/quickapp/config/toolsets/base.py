from pydantic import BaseModel, Field

from quickapp.common.localized_string import LocalizedString


class BaseToolSet(BaseModel):
    """
    Represents a base toolset configuration.

    A toolset can either be:
    - A physical abstraction on top of a set of tools (e.g., Web API Toolset or MCP Server Toolset).
    - A logical abstraction on top of separate tools and physical toolsets.
    """

    name: LocalizedString = Field(description="The name of the tool set.")
    description: LocalizedString | None = Field(
        default=None, description="The description of the tool set."
    )
    enabled: bool = Field(default=True, description="Whether the toolset is enabled.")
