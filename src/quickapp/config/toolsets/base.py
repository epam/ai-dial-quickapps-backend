from pydantic import BaseModel, Field

from quickapp.common.base_config import PreviewField
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
    deferred: bool | None = PreviewField(  # type: ignore[assignment]
        default=None,
        json_schema_extra={"default": True},
        description=(
            "When true or unset, this toolset's tool schemas are withheld from the initial LLM payload. "
            "Requires orchestrator.tool_discovery.enabled=true. "
            "Tools are discovered on demand via the tool_search meta-tool. "
            "Set to false to keep this toolset always eager."
        ),
    )
