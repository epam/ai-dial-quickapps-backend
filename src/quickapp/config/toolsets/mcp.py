from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quickapp.common.base_config import PreviewField
from quickapp.config.tools.base import AttachmentConfig
from quickapp.config.tools.tool_fallback import ToolFallbackConfig
from quickapp.config.toolsets.authorization import (
    BasicAuthorization,
    ClientIdSecretAuthorization,
    MCPApiKeyAuthorization,
)
from quickapp.config.toolsets.base import BaseToolSet
from quickapp.config.toolsets.hidden_from_model import (
    HIDDEN_FROM_MODEL_DESCRIPTION,
    validate_hidden_from_model,
)
from quickapp.config.toolsets.rest_api import BearerAuthorization

Authorization = Annotated[
    BearerAuthorization | MCPApiKeyAuthorization | ClientIdSecretAuthorization | BasicAuthorization,
    Field(discriminator="type"),
]


class MCPProtocol(str, Enum):
    sse = "sse"
    streamable_http = "streamable_http"


class MCPResourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    uri: str
    eager: bool = Field(
        default=False,
        description=(
            "Pre-fetch this resource at init time and inject its content as a "
            "synthetic read_mcp_resource tool call pair before the first LLM invocation."
        ),
    )


class MCPResourcesConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(default=False)
    items: list[MCPResourceConfig] | None = Field(
        default=None,
        description=(
            "Resources to expose. None = expose all resources the server declares, all lazy. "
            "Provide a list to restrict to specific URIs and/or mark some as eager."
        ),
    )


class MCPServerInfo(BaseModel):
    url: str = Field(description="URL of the MCP server")
    authorization: Authorization | None = None
    protocol: MCPProtocol


class MCPToolSet(BaseToolSet):
    type: Literal["mcp"] = Field(default="mcp", description="The type of the tool set.")
    mcp_server_info: MCPServerInfo
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
