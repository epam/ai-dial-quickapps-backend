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
            description=("""
Purpose: Discover additional tools and capabilities.

You MUST call this tool before stating any limitation or saying you cannot fulfill a user request.

In addition, you MUST call this tool whenever:
- The user’s request is open-ended or underspecified.
- The request might involve capabilities beyond your currently listed tools.
- The request could plausibly be served by a specialized tool or by returning a resource, even if you believe you can respond text-only.

If a user request might involve capabilities beyond your current listed tools, you are REQUIRED to:
1) Call internal_tool_search with a brief description of the needed capability.
2) Inspect any returned tools.

You may NOT:
- Assume that the initially listed tools are exhaustive.
- Say "I can't", "I don't have access", or express similar limitations until you have called internal_tool_search in this conversation turn.

Only if internal_tool_search returns no suitable tools, or all relevant tools fail, may you tell the user you cannot do it.

This tool dynamically discovers additional toolsets (including hidden or MCP tools) that may provide additional capabilities:
"""),
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
