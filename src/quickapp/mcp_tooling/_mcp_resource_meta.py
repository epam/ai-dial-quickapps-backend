from pydantic import BaseModel, ConfigDict


class MCPResourceMeta(BaseModel):
    model_config = ConfigDict(frozen=True)

    toolset_name: str
    toolset_description: str | None
    resource_name: str
    resource_uri: str
    resource_description: str | None = None
    mime_type: str | None = None
