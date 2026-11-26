from quickapp.common.utils import fenced_code_block

from .initialization import InitializationException


class ToolInitializationException(InitializationException):
    """Raised when a tool or toolset fails to initialize properly."""

    def __init__(
        self, message: str, tool_name: str = "", toolset_name: str = "", details: str = ""
    ):
        super().__init__(
            f"Initialization Error: {message}" + (f" for Tool: {tool_name}" if tool_name else "")
        )
        self.message = message
        self.tool_name = tool_name
        self.toolset_name = toolset_name
        self.details = details

    @property
    def user_facing_message(self) -> str:
        message = f"**{self.tool_name}{self.toolset_name}**: {self}"
        return f"{message}\n{fenced_code_block(self.details)}" if self.details else message
