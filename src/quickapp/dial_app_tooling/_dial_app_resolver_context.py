from quickapp.common.exceptions import ToolInitializationException
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.toolsets.mcp import MCPToolSet


class _DialAppResolverContext:
    """Request-scoped holder for DialAppToolSet resolution outputs."""

    def __init__(self):
        self._resolved_mcp_toolsets: list[MCPToolSet] = []
        self._resolved_deployment_tools: list[tuple[str, DialDeploymentTool]] = []
        self._exceptions: list[ToolInitializationException] = []

    @property
    def resolved_mcp_toolsets(self) -> list[MCPToolSet]:
        return self._resolved_mcp_toolsets

    @property
    def resolved_deployment_tools(self) -> list[tuple[str, DialDeploymentTool]]:
        return self._resolved_deployment_tools

    @property
    def exceptions(self) -> list[ToolInitializationException]:
        return self._exceptions

    def append_mcp_toolset(self, toolset: MCPToolSet) -> None:
        self._resolved_mcp_toolsets.append(toolset)

    def append_deployment_tool(self, toolset_name: str, tool: DialDeploymentTool) -> None:
        self._resolved_deployment_tools.append((toolset_name, tool))

    def append_exception(self, exception: ToolInitializationException) -> None:
        self._exceptions.append(exception)
