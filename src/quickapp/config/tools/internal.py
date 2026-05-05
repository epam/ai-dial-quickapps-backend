from typing import Literal

from pydantic import Field

from quickapp.config.tools.base import BaseOpenAITool


class InternalTool(BaseOpenAITool):
    type: Literal["internal-tool"] = Field(default="internal-tool")
    defer_stage_close: bool = Field(
        default=False,
        description=(
            "When True, the tool stage closes after parallel tool execution completes "
            "instead of when this tool returns."
        ),
    )
