from quickapp.common.tooling_context_base import ToolingContextBase
from quickapp.mcp_tooling._mcp_eager_resource import MCPEagerResource
from quickapp.mcp_tooling._mcp_resource_meta import MCPResourceMeta
from quickapp.mcp_tooling._mcp_server_capabilities import MCPServerCapabilities
from quickapp.mcp_tooling._mcp_toolset_client import _MCPToolsetClient


class _MCPToolingContext(ToolingContextBase):
    def __init__(self) -> None:
        super().__init__()
        self._resource_metas: list[MCPResourceMeta] = []
        self._eager_resources: list[MCPEagerResource] = []
        self._server_capabilities: list[MCPServerCapabilities] = []
        # toolset_name -> _MCPToolsetClient; populated during init for _ReadMcpResourceTool
        self._clients: dict[str, _MCPToolsetClient] = {}

    def extend_resource_metas(self, metas: list[MCPResourceMeta]) -> None:
        with self._lock:
            self._resource_metas.extend(metas)

    def extend_eager_resources(self, resources: list[MCPEagerResource]) -> None:
        with self._lock:
            self._eager_resources.extend(resources)

    def extend_server_capabilities(self, caps: list[MCPServerCapabilities]) -> None:
        with self._lock:
            self._server_capabilities.extend(caps)

    def register_client(self, toolset_name: str, client: _MCPToolsetClient) -> None:
        with self._lock:
            self._clients[toolset_name] = client

    @property
    def resource_metas(self) -> list[MCPResourceMeta]:
        return self._resource_metas

    @property
    def eager_resources(self) -> list[MCPEagerResource]:
        return self._eager_resources

    @property
    def server_capabilities(self) -> list[MCPServerCapabilities]:
        return self._server_capabilities

    @property
    def clients(self) -> dict[str, _MCPToolsetClient]:
        return self._clients
