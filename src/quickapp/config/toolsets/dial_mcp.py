from typing import Annotated, Literal

from pydantic import Field

from quickapp.common.base_config import DialResourceConfigField, LegacyAlias, LegacyAliasModel
from quickapp.config.tools.base import AttachmentConfig
from quickapp.config.tools.tool_fallback import ToolFallbackConfig
from quickapp.config.toolsets.base import BaseToolSet


class DialMCPToolSet(BaseToolSet, LegacyAliasModel):
    type: Literal["dial-mcp"] = Field(default="dial-mcp", description="The type of the tool set.")
    # Override name of BaseToolSet. UI team doesn't send us this field.
    name: str = Field(default="untitled-mcp-toolset", description="default name of the toolset")
    deployment_id: Annotated[
        str,
        DialResourceConfigField(
            description="The id of the DIAL deployment associated with this MCP toolset.",
        ),
        LegacyAlias("dial_id"),
    ]
    # Deprecated. This field is read from DialCore. This value is ignored and should be removed.
    transport: Literal["HTTP", "SSE"] = Field(
        default="HTTP", description="The transport type of the tool set."
    )
    allowed_tools: list[str] | None = Field(
        default=None, description="Allowed MCP tool names from the server"
    )
    attachment: AttachmentConfig = Field(
        default_factory=AttachmentConfig, description="Configuration for toolset attachments."
    )
    fallback_configuration: ToolFallbackConfig = Field(
        default_factory=ToolFallbackConfig, description="Tool fallback configuration."
    )
