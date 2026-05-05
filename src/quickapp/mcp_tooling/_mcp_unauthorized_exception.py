class MCPUnauthorizedException(Exception):
    """Raised when an MCP connection or tool call returns HTTP 401 Unauthorized."""

    def __init__(self, toolset_name: str):
        super().__init__(f"Authentication required for toolset '{toolset_name}'")
        self.toolset_name = toolset_name
