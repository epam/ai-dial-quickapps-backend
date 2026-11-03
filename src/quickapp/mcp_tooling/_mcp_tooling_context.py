from quickapp.common import StagedBaseTool
from quickapp.common.deferred_tools_accumulator import DeferredToolsAccumulator
from quickapp.common.tooling_context_base import ToolingContextBase
from quickapp.mcp_tooling._mcp_eager_resource import MCPEagerResource
from quickapp.mcp_tooling._mcp_resource_meta import MCPResourceMeta
from quickapp.mcp_tooling._mcp_server_capabilities import MCPServerCapabilities
from quickapp.mcp_tooling._mcp_toolset_client import _MCPToolsetClient


class _MCPToolingContext(ToolingContextBase, DeferredToolsAccumulator):
    def __init__(self) -> None:
        ToolingContextBase.__init__(self)
        DeferredToolsAccumulator.__init__(self)
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

    # Toolsets load in parallel and publish in completion order; sort so the
    # prompt-cache prefix stays byte-stable across requests.
    @property
    def tools(self) -> list[StagedBaseTool]:
        return sorted(self._tools, key=lambda t: t.openai_function_name() or "")

    @property
    def resource_metas(self) -> list[MCPResourceMeta]:
        return sorted(self._resource_metas, key=lambda m: m.toolset_name)

    @property
    def eager_resources(self) -> list[MCPEagerResource]:
        return sorted(self._eager_resources, key=lambda r: r.toolset_name)

    @property
    def server_capabilities(self) -> list[MCPServerCapabilities]:
        return self._server_capabilities

    @property
    def clients(self) -> dict[str, _MCPToolsetClient]:
        return self._clients
