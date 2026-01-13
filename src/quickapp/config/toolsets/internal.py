from typing import Literal

from pydantic import Field

from quickapp.config.tools.internal import InternalTool
from quickapp.config.tools.predefined import PredefinedTool
from quickapp.config.toolsets.base import BaseToolSet


class InternalToolSet(BaseToolSet):
    type: Literal["internal"] = Field(default="internal", description="The type of the tool set.")
    tools: list[InternalTool | PredefinedTool] = Field(
        description="Tools with their configurations."
    )
