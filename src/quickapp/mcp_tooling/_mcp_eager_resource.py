from typing import Literal

from quickapp.mcp_tooling._mcp_resource_meta import MCPResourceMeta


class MCPEagerTextResource(MCPResourceMeta):
    content_type: Literal["text"] = "text"
    text: str


# Phase 2 will add MCPEagerBlobResource with dial_url for AttachmentService upload.
MCPEagerResource = MCPEagerTextResource
