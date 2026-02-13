from quickapp.config.tools.base import (
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool

INTERNAL_TOOL_NAME_PREFIX = "quickapps_internal_"


AVAILABLE_CONTEXT_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=f"{INTERNAL_TOOL_NAME_PREFIX}available_context",
            description=(
                "Returns metadata about admin-configured context files"
                " attached to this application."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={},
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Available context")),
)

# Tool name after hashing by OpenAiToolFunction.set_name validator
AVAILABLE_CONTEXT_TOOL_NAME = AVAILABLE_CONTEXT_TOOL_CONFIG.open_ai_tool.function.name
