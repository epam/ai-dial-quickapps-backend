from quickapp.config.subagent import SubagentConfig
from quickapp.config.tools.base import (
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool

SPAWN_TOOL_NAME = "spawn_subagent"


def build_spawn_tool_config(subagents: list[SubagentConfig]) -> InternalTool:
    """One tool for every declared subagent type, selected by ``subagent_type``.

    Matches Claude Code's shape: a flat tool catalogue that does not grow as the
    builder adds subagent types, with routing carried by the enum descriptions.
    """
    catalogue = "\n".join(f"- {s.name}: {s.description}" for s in subagents)
    return InternalTool(
        open_ai_tool=OpenAiToolConfig(
            function=OpenAiToolFunction(
                name=SPAWN_TOOL_NAME,
                description=(
                    "Delegate a self-contained task to a subagent. The subagent works in "
                    "its own isolated context and returns only its final answer — its "
                    "intermediate steps never enter this conversation. Available subagents:\n"
                    f"{catalogue}"
                ),
                parameters=OpenAiToolFunctionParameters(
                    type=JsonTypeEnum.object,
                    properties={
                        "subagent_type": ConfigurableSchemaSimpleType(
                            type=JsonTypeEnum.string,
                            description="Which subagent to spawn.",
                            enum=[s.name for s in subagents],
                        ),
                        "task": ConfigurableSchemaSimpleType(
                            type=JsonTypeEnum.string,
                            description=(
                                "The complete task for the subagent. It sees nothing but "
                                "this text — no conversation history, no other subagent's "
                                "work — so state everything it needs."
                            ),
                        ),
                    },
                    required=["subagent_type", "task"],
                ),
            )
        ),
        display=ToolDisplayConfig(stage=ToolStageConfig(name="Subagent")),
    )
