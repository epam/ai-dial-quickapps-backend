from pydantic import BaseModel, ConfigDict


class MCPServerCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    toolset_name: str
    server_name: str
    server_version: str
    protocol_version: str
    supports_tools: bool
    supports_resources: bool
    supports_prompts: bool
