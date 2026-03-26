from typing import Literal

from pydantic import Field

from quickapp.config.tools.base import BaseOpenAITool

INTERNAL_TOOL_NAME_PREFIX = "quickapps_internal_"


class InternalTool(BaseOpenAITool):
    type: Literal["internal-tool"] = Field(default="internal-tool")
