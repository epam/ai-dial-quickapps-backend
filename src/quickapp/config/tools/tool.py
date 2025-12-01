from typing import Annotated

from pydantic import Field

from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.tools.deployment_simple import DialDeploymentSimpleTool
from quickapp.config.tools.internal import InternalTool
from quickapp.config.tools.mcp import MCPTool
from quickapp.config.tools.predefined import PredefinedTool
from quickapp.config.tools.rest_api import RestApiTool

AnyTool = Annotated[
    DialDeploymentTool
    | InternalTool
    | RestApiTool
    | MCPTool
    | PredefinedTool
    | DialDeploymentSimpleTool,
    Field(discriminator="type"),
]
