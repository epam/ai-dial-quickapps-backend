from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT_TOOL_NAME
from quickapp.config.tools.base import (
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
