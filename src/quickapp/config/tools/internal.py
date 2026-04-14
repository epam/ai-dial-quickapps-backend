from typing import Literal

from pydantic import Field

from quickapp.config.tools.base import BaseOpenAITool


class InternalTool(BaseOpenAITool):
    type: Literal["internal-tool"] = Field(default="internal-tool")
