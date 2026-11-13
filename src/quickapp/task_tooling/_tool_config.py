from typing import Any

from quickapp.common.tool_names import INTERNAL_RUN_TASK_TOOL_NAME
from quickapp.config.tools.base import (
    ConfigurableSchemaArray,
    ConfigurableSchemaSimpleType,
    JsonSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool
from quickapp.config.tools.tool_fallback import ContinueStrategyModel, ToolFallbackConfig

# Reserved single item of `tools`: the schema models have no `anyOf`, so the
# "inherit" | list[str] union is carried by an array.
INHERIT_TOOLS = "inherit"


def is_inherit(tools: Any) -> bool:
    """Whether `tools` asks for every tool: ``["inherit"]`` or a bare ``"inherit"``."""
    return tools == INHERIT_TOOLS or tools == [INHERIT_TOOLS]


RUN_TASK_TOOL_CONFIG = InternalTool(
    # Validation and task errors are forwarded to the model so it can retry.
    fallback_configuration=ToolFallbackConfig(
        strategies=[ContinueStrategyModel()],
    ),
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=INTERNAL_RUN_TASK_TOOL_NAME,
            description=(
                "Run a self-contained task in an isolated context and get back only its "
                "final answer — its intermediate steps never enter this conversation. "
                "Use it when a sub-task would take several tool calls whose intermediate "
                "results you do not need. Independent tasks can run in parallel: call "
                "this tool several times in one turn."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "name": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="A short (3-5 word) label for the task, shown to the user.",
                    ),
                    "prompt": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "The complete task. The task sees nothing but this text — no "
                            "conversation history, no other task's work — so state "
                            "everything it needs and what its answer should contain."
                        ),
                    ),
                    "tools": ConfigurableSchemaArray(
                        type=JsonTypeEnum.array,
                        description=(
                            f'["{INHERIT_TOOLS}"] gives the task all of your tools. '
                            "Otherwise list the exact names of the tools from your own tool "
                            "list that the task may use; it gets those and nothing else. "
                            "Pass [] for a task that only reasons over the text you give it."
                        ),
                        items=JsonSchemaSimpleType(type=JsonTypeEnum.string),
                    ),
                },
                required=["name", "prompt", "tools"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Task")),
)
