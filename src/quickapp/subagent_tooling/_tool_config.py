from quickapp.common.localized_string import resolve_localized
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
from quickapp.config.toolsets.predefined import PredefinedToolSet
from quickapp.config.toolsets.toolset import ToolSet

from ._builtin_subagents import GENERAL_PURPOSE_DESCRIPTION
from ._manifest_compiler import tool_set_name

# Tool name and the free-text parameter (``prompt``) mirror Anthropic's Claude Code
# "Task" tool, so builders and models familiar with it find the same shape here.
TASK_TOOL_NAME = "task"

_TOOL_SETS_DESCRIPTION = (
    "Which of this app's tool sets the subagent may use. It gets these and nothing "
    "else — it does not inherit your tools, so name every set the task needs. Pass an "
    "empty list for a subagent that only has to reason over the text you give it."
)


def _catalogue(tool_sets: list[ToolSet]) -> str:
    """A ``- name: description`` line per tool set.

    The coordinator knows which *tools* it holds but not which *set* each belongs to,
    so the enum alone would leave it guessing. Descriptions are optional in config;
    a set without one is still listed, by name.
    """
    lines = []
    for tool_set in tool_sets:
        if isinstance(tool_set, PredefinedToolSet):
            continue
        name = tool_set_name(tool_set)
        description = resolve_localized(tool_set.description) if tool_set.description else None
        lines.append(f"- {name}: {description}" if description else f"- {name}")
    return "\n".join(lines)


def build_spawn_tool_config(tool_sets: list[ToolSet]) -> InternalTool:
    """The `task` tool: one general-purpose subagent, scoped per call.

    ``tool_sets`` is required rather than optional so that handing a spoke no tools is
    always a deliberate choice. A model that simply forgot the argument would otherwise
    get a tool-less agent, which does not fail — it answers from the prompt alone and
    sounds confident doing it.
    """
    catalogue = _catalogue(tool_sets)
    names = [name for ts in tool_sets if (name := tool_set_name(ts))]

    return InternalTool(
        open_ai_tool=OpenAiToolConfig(
            function=OpenAiToolFunction(
                name=TASK_TOOL_NAME,
                description=(
                    f"{GENERAL_PURPOSE_DESCRIPTION} The subagent works in its own "
                    "isolated context and returns only its final answer — its "
                    "intermediate steps never enter this conversation. You choose which "
                    "tools it gets for each task."
                ),
                parameters=OpenAiToolFunctionParameters(
                    type=JsonTypeEnum.object,
                    properties={
                        "prompt": ConfigurableSchemaSimpleType(
                            type=JsonTypeEnum.string,
                            description=(
                                "The complete task for the subagent. It sees nothing but "
                                "this text — no conversation history, no other subagent's "
                                "work — so state everything it needs."
                            ),
                        ),
                        "tool_sets": ConfigurableSchemaArray(
                            type=JsonTypeEnum.array,
                            description=(
                                f"{_TOOL_SETS_DESCRIPTION}\nAvailable tool sets:\n{catalogue}"
                                if catalogue
                                else _TOOL_SETS_DESCRIPTION
                            ),
                            items=JsonSchemaSimpleType(
                                type=JsonTypeEnum.string,
                                # An empty `enum` is not valid JSON Schema, so an app with
                                # no tool sets leaves the item unconstrained instead.
                                enum=names or None,
                            ),
                        ),
                    },
                    required=["prompt", "tool_sets"],
                ),
            )
        ),
        display=ToolDisplayConfig(stage=ToolStageConfig(name="Subagent")),
    )
