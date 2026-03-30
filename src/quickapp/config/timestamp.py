from typing import Literal

from pydantic import BaseModel


class ToolCallTimestampConfig(BaseModel):
    injection_strategy: Literal["tool_call"] = "tool_call"


# Type alias — currently a single variant.  When a second strategy is added
# (e.g. SystemPromptTimestampConfig), change this to a discriminated union:
#   TimestampConfig = Annotated[
#       ToolCallTimestampConfig | SystemPromptTimestampConfig,
#       Discriminator("injection_strategy"),
#   ]
TimestampConfig = ToolCallTimestampConfig
