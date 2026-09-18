from quickapp.common.localized_string import resolve_localized
from quickapp.config.subagent import GENERAL_PURPOSE_SUBAGENT_NAME, SubagentsConfig
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
    f"Only for `{GENERAL_PURPOSE_SUBAGENT_NAME}`, where it is required: which of this "
    "app's tool sets the subagent may use. It gets these and nothing else — it does not "
    "inherit your tools, so name every set the task needs. Pass an empty list for a "
    "subagent that only has to reason over the text you give it. Omit for any other "
    "subagent type; those have a fixed tool set."
)


def _tool_set_catalogue(tool_sets: list[ToolSet]) -> str:
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


def _subagent_catalogue(config: SubagentsConfig) -> list[tuple[str, str]]:
    """``(name, description)`` per offered subagent, the built-in one first."""
    catalogue = []
    if config.general_purpose is not None:
        catalogue.append((GENERAL_PURPOSE_SUBAGENT_NAME, GENERAL_PURPOSE_DESCRIPTION))
    catalogue.extend((s.name, s.description) for s in config.types)
    return catalogue


def build_spawn_tool_config(config: SubagentsConfig, tool_sets: list[ToolSet]) -> InternalTool:
    """One `task` tool for every offered subagent, selected by ``subagent_type``.

    A flat tool catalogue that does not grow as the builder adds subagent types:
    routing is carried by the enum and the per-subagent descriptions, and the
    ``prompt`` parameter carries the delegated task. ``tool_sets`` — the app's
    selectable tool sets — is offered only when the general-purpose subagent is, since
    it is the one whose tools the coordinator picks per call.
    """
    subagents = _subagent_catalogue(config)
    properties: dict[str, ConfigurableSchemaSimpleType | ConfigurableSchemaArray] = {
        "subagent_type": ConfigurableSchemaSimpleType(
            type=JsonTypeEnum.string,
            description="Which subagent to spawn.",
            enum=[name for name, _ in subagents],
        ),
        "prompt": ConfigurableSchemaSimpleType(
            type=JsonTypeEnum.string,
            description=(
                "The complete task for the subagent. It sees nothing but "
                "this text — no conversation history, no other subagent's "
                "work — so state everything it needs."
            ),
        ),
    }
    if config.general_purpose is not None:
        catalogue = _tool_set_catalogue(tool_sets)
        names = [name for ts in tool_sets if (name := tool_set_name(ts))]
        properties["tool_sets"] = ConfigurableSchemaArray(
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
        )

    return InternalTool(
        open_ai_tool=OpenAiToolConfig(
            function=OpenAiToolFunction(
                name=TASK_TOOL_NAME,
                description=(
                    "Delegate a self-contained task to a subagent. The subagent works in "
                    "its own isolated context and returns only its final answer — its "
                    "intermediate steps never enter this conversation. Available subagents:\n"
                    + "\n".join(f"- {name}: {description}" for name, description in subagents)
                ),
                parameters=OpenAiToolFunctionParameters(
                    type=JsonTypeEnum.object,
                    properties=properties,
                    required=["subagent_type", "prompt"],
                ),
            )
        ),
        display=ToolDisplayConfig(stage=ToolStageConfig(name="Subagent")),
    )
