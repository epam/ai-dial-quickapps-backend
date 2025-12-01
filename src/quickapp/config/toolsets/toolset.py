from typing import Annotated

from pydantic import Field

from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.config.toolsets.dial_mcp import DialMCPToolSet
from quickapp.config.toolsets.internal import InternalToolSet
from quickapp.config.toolsets.mcp import MCPToolSet
from quickapp.config.toolsets.predefined import PredefinedToolSet
from quickapp.config.toolsets.rest_api import RestApiToolSet

ToolSet = Annotated[
    RestApiToolSet
    | DeploymentToolSet
    | InternalToolSet
    | MCPToolSet
    | DialMCPToolSet
    | PredefinedToolSet,
    Field(discriminator="type"),
]
