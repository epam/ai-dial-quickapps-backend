from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from quickapp.config.tools.base import AttachmentConfig
from quickapp.config.tools.tool_fallback import ToolFallbackConfig
from quickapp.config.toolsets.authorization import (
    BasicAuthorization,
    ClientIdSecretAuthorization,
    MCPApiKeyAuthorization,
)
from quickapp.config.toolsets.base import BaseToolSet
from quickapp.config.toolsets.rest_api import BearerAuthorization

Authorization = Annotated[
    Union[
        BearerAuthorization, MCPApiKeyAuthorization, ClientIdSecretAuthorization, BasicAuthorization
    ],
    Field(discriminator="type"),
]


class MCPProtocol(str, Enum):
    sse = "sse"
    streamable_http = "streamable_http"


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
    attachment: AttachmentConfig = Field(
        default_factory=AttachmentConfig, description="Configuration for toolset attachments."
    )
    fallback_configuration: ToolFallbackConfig = Field(
        default_factory=ToolFallbackConfig, description="Tool fallback configuration."
    )
