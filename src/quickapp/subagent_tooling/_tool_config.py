from quickapp.config.subagent import SubagentsConfig
from quickapp.config.tools.base import (
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool

# ``prompt`` parameter mirrors Anthropic's Claude Code "Task" tool shape so
# builders and models familiar with it find the same interface here.
TASK_TOOL_NAME = "internal_task"


def _subagent_listing(config: SubagentsConfig) -> str:
    return "\n".join(f"- {s.name}: {s.description}" for s in config.types)


def build_spawn_tool_config(config: SubagentsConfig) -> InternalTool:
    """One `task` tool for every declared subagent type, selected by ``subagent_type``.

    A flat tool catalogue that does not grow as the builder adds subagent types:
    routing is carried by the enum and the per-subagent descriptions, and the
    ``prompt`` parameter carries the delegated task.
    """
    return InternalTool(
        open_ai_tool=OpenAiToolConfig(
            function=OpenAiToolFunction(
                name=TASK_TOOL_NAME,
                description=(
                    "Delegate a self-contained task to a subagent. The subagent works in "
                    "its own isolated context and returns only its final answer — its "
                    "intermediate steps never enter this conversation. Available subagents:\n"
                    + _subagent_listing(config)
                ),
                parameters=OpenAiToolFunctionParameters(
                    type=JsonTypeEnum.object,
                    properties={
                        "subagent_type": ConfigurableSchemaSimpleType(
                            type=JsonTypeEnum.string,
                            description="Which subagent to spawn.",
                            enum=[s.name for s in config.types],
                        ),
                        "prompt": ConfigurableSchemaSimpleType(
                            type=JsonTypeEnum.string,
                            description=(
                                "The complete task for the subagent. It sees nothing but "
                                "this text — no conversation history, no other subagent's "
                                "work — so state everything it needs."
                            ),
                        ),
                    },
                    required=["subagent_type", "prompt"],
                ),
            )
        ),
        display=ToolDisplayConfig(stage=ToolStageConfig(name="Subagent")),
    )
