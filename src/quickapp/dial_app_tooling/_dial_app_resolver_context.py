from quickapp.common.exceptions import InitializationException, ToolInitializationException
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.toolsets.mcp import MCPToolSet


class _DialAppResolverContext:
    """Request-scoped holder for DialAppToolSet resolution outputs."""

    def __init__(self):
        self._resolved_mcp_toolsets: list[MCPToolSet] = []
        self._resolved_deployment_tools: list[DialDeploymentTool] = []
        self._exceptions: list[InitializationException] = []

    @property
    def resolved_mcp_toolsets(self) -> list[MCPToolSet]:
        return self._resolved_mcp_toolsets

    @property
    def resolved_deployment_tools(self) -> list[DialDeploymentTool]:
        return self._resolved_deployment_tools

    @property
    def exceptions(self) -> list[InitializationException]:
        return self._exceptions

    def append_mcp_toolset(self, toolset: MCPToolSet) -> None:
        self._resolved_mcp_toolsets.append(toolset)

    def append_deployment_tool(self, tool: DialDeploymentTool) -> None:
        self._resolved_deployment_tools.append(tool)

    def append_exception(self, exception: ToolInitializationException) -> None:
        self._exceptions.append(exception)
