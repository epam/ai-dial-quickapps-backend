from quickapp.common.tool_names import (
    INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT_TOOL_NAME,
    INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
)
from quickapp.config.tools.base import (
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool

GET_CONTENT_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
            description=(
                "Loads one allowed attachment by URL for use in this turn. "
                f"Pass the exact `url` string from the "
                f"`{INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT_TOOL_NAME}` tool "
                "result (`entries[].url`) or from user `<attachments>` metadata in messages. "
                "Only URLs from current admin contexts or user attachments are accepted; arbitrary paths or URLs are rejected. "
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "attachment_url": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Exact file `url` from `internal_attachments_available_context.entries[].url` "
                            "or from user `<attachments>` section (same string, including path). "
                        ),
                    )
                },
                required=["attachment_url"],
            ),
        )
    ),
    display=ToolDisplayConfig(
        stage=ToolStageConfig(name="Get context content", show=True, defer_close=True),
    ),
)
