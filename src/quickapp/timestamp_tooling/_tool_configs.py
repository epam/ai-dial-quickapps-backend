from quickapp.config.tools.base import (
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool

SYNTHETIC_TIMESTAMP_CALL_PREFIX = "call_synthetic_timestamp_"

CURRENT_TIMESTAMP_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name="internal_timeawareness_current_timestamp",
            description="Returns the current date and time. Optionally converts to a specific timezone.",
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "timezone": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="IANA timezone name (e.g. 'Asia/Tokyo'). Defaults to UTC.",
                    )
                },
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Current timestamp")),
)

# Tool name as sent to the LLM (sanitized, no hash)
CURRENT_TIMESTAMP_TOOL_NAME = CURRENT_TIMESTAMP_TOOL_CONFIG.open_ai_tool.function.name
