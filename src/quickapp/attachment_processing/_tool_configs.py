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

AVAILABLE_CONTEXT_TOOL_NAME = INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT_TOOL_NAME

AVAILABLE_CONTEXT_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=AVAILABLE_CONTEXT_TOOL_NAME,
            description=(
                "Returns metadata about admin-configured context files."
                " **IMPORTANT**: this tool is not applicable to user-attached files or files from tool results, "
                "and will not return any information about them. If you see file in <attachments> section of user "
                "message, it means that the file was attached by the user, and is available for you to use."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={},
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Available context")),
)

GET_CONTENT_TOOL_CONFIG = InternalTool(
    defer_stage_close=True,
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
            description=(
                "Loads one allowed attachment by URL for use in this turn. "
                f"Pass the exact `url` string from the `{AVAILABLE_CONTEXT_TOOL_NAME}` tool "
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
                            "Legacy alias `context_url` is still accepted."
                        ),
                    )
                },
                required=["attachment_url"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Get context content", show=True)),
)
