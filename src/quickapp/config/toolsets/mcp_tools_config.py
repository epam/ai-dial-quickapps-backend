from typing import Any

from pydantic import BaseModel, ConfigDict, Field

FIXED_ARGUMENTS_DESCRIPTION = (
    "Argument values fixed for this tool: {argument: value}. Fixed arguments are removed from the "
    "schema the model sees and added to every call, overriding any value the caller sends. "
    "Top-level arguments only. Values are stored in plain text in the app config: do not use "
    "this for secrets."
)

TOOLS_CONFIG_DESCRIPTION = (
    "Per-tool settings, keyed by MCP tool name (as the server reports it). "
    "When allowed_tools is set, every key must be listed there."
)


class MCPToolConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fixed_arguments: dict[str, Any] | None = Field(
        default=None, description=FIXED_ARGUMENTS_DESCRIPTION
    )
