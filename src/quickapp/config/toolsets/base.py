from pydantic import BaseModel, Field


class BaseToolSet(BaseModel):
    """
    Represents a base toolset configuration.

    A toolset can either be:
    - A physical abstraction on top of a set of tools (e.g., Web API Toolset or MCP Server Toolset).
    - A logical abstraction on top of separate tools and physical toolsets.
    """

    name: str = Field(description="The name of the tool set.")
    description: str | None = Field(default=None, description="The description of the tool set.")
    enabled: bool = Field(default=True, description="Whether the toolset is enabled.")
