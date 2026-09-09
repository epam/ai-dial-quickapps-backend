from quickapp.common.tool_names import INTERNAL_TOOL_SEARCH_TOOL_NAME
from quickapp.config.tools.base import (
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool

TOOL_SEARCH_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=INTERNAL_TOOL_SEARCH_TOOL_NAME,
            description=(
                "Search for additional tools available to this assistant. "
                "Use this when you need a capability that is not listed in the current tool list. "
                "Returns the names and descriptions of matching tools; "
                "those tools will be available to call immediately after."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "query": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="A natural-language description of the capability you need.",
                    )
                },
                required=["query"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Searching tools")),
)
