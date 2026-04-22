from quickapp.config.tools.base import (
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool

INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME = "internal_attachments_get_content"
AVAILABLE_CONTEXT_TOOL_NAME = "internal_attachments_available_context"

AVAILABLE_CONTEXT_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=AVAILABLE_CONTEXT_TOOL_NAME,
            description=(
                "Returns metadata about admin-configured context files (title, url, type). "
                f"If you are able to work with such attachments on your own, call `{INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME}` with the "
                "exact `url` string from an entry. "
                "**IMPORTANT**: this tool is not applicable to user-attached files or files from tool results, "
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
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
            description=(
                "Loads one admin-configured context file by URL for use in this turn. "
                f"Pass the exact `url` string from the `{AVAILABLE_CONTEXT_TOOL_NAME}` tool "
                "result (`entries[].url`). "
                "Only URLs listed there are accepted; arbitrary paths or URLs are rejected. "
                "If the orchestrator model does not support attachment type, this tool may be unavailable even "
                "when files are configured."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "context_url": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Exact `url` value from an entry returned by "
                            "`internal_attachments_available_context` (same string, including path)."
                        ),
                    )
                },
                required=["context_url"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Get context content", show=True)),
)
