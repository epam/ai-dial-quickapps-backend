from typing import Literal

from pydantic import Field

from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.tools.deployment_simple import DialDeploymentSimpleTool
from quickapp.config.tools.predefined import PredefinedTool
from quickapp.config.toolsets.base import BaseToolSet
from quickapp.config.toolsets.forwarded_headers_config import ForwardedHeadersMixin


class DeploymentToolSet(BaseToolSet, ForwardedHeadersMixin):
    type: Literal["dial-deployment"] = Field(
        default="dial-deployment", description="The type of the tool set."
    )
    tools: list[DialDeploymentTool | DialDeploymentSimpleTool | PredefinedTool] = Field(
        description="Tools with their configurations."
    )
