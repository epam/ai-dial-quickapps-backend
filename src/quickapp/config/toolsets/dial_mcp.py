from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from quickapp.common.base_config import (
    DialResourceConfigField,
    LegacyAlias,
    LegacyAliasModel,
    PreviewField,
)
from quickapp.config.tools.base import AttachmentConfig
from quickapp.config.tools.tool_fallback import ToolFallbackConfig
from quickapp.config.toolsets.base import BaseToolSet
from quickapp.config.toolsets.hidden_from_model import (
    HIDDEN_FROM_MODEL_DESCRIPTION,
    validate_hidden_from_model,
)
from quickapp.config.toolsets.mcp import MCPResourcesConfig


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
    hidden_from_model: list[str] | None = PreviewField(  # type: ignore[assignment]
        default=None, description=HIDDEN_FROM_MODEL_DESCRIPTION
    )
    attachment: AttachmentConfig = Field(
        default_factory=AttachmentConfig, description="Configuration for toolset attachments."
    )
    fallback_configuration: ToolFallbackConfig = Field(
        default_factory=ToolFallbackConfig, description="Tool fallback configuration."
    )
    resources: MCPResourcesConfig | None = Field(default=None)

    @model_validator(mode="after")
    def _validate_hidden_from_model(self) -> Self:
        validate_hidden_from_model(self.allowed_tools, self.hidden_from_model)
        return self
