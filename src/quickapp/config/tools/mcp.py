from typing import Literal

from pydantic import Field

from quickapp.config.tools.base import BaseOpenAITool


class MCPTool(BaseOpenAITool):
    type: Literal["mcp-tool"] = Field(default="mcp-tool")
