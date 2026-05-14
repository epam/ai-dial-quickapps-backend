import logging
import os
from collections.abc import Callable
from typing import Any, TypeAlias, cast

from pydantic import TypeAdapter

from quickapp.common.exceptions import ConfigResolutionException
from quickapp.config.tools.predefined import PredefinedTool
from quickapp.config.tools.tool import AnyTool
from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.config.toolsets.internal import InternalToolSet
from quickapp.config.toolsets.rest_api import RestApiToolSet
from quickapp.config.toolsets.toolset import ToolSet

logger = logging.getLogger(__name__)

HostingToolSet: TypeAlias = RestApiToolSet | DeploymentToolSet | InternalToolSet

HOSTING_TOOLSET_TYPES: tuple[type[HostingToolSet], ...] = (
    RestApiToolSet,
    DeploymentToolSet,
    InternalToolSet,
)

_TOOLSET_ADAPTER: TypeAdapter[ToolSet] = TypeAdapter(ToolSet)


def bool_env_var(param: str, default: bool) -> bool:
    """Read a boolean env var. Prefer per-module pydantic Settings for app configuration."""
    value = os.getenv(param, str(default)).lower()
    if value not in ["true", "false"]:
        logger.warning("Env variable `%s` has invalid boolean value `%s`", param, value)
    return value == "true"


def expand_predefined_tools(
    tool_set: ToolSet,
    *,
    resolve_tool: Callable[[PredefinedTool], AnyTool],
    on_predefined_tool_error: Callable[[PredefinedTool, ConfigResolutionException], None],
) -> ToolSet:
    """Expand ``predefined-tool`` entries inside hosting toolsets; mutate ``tool_set`` in place."""
    if not isinstance(tool_set, HOSTING_TOOLSET_TYPES):
        return tool_set
    resolved_tools: list[AnyTool] = []
    for tool in tool_set.tools:
        if isinstance(tool, PredefinedTool) and tool.enabled:
            try:
                resolved_tools.append(resolve_tool(tool))
            except ConfigResolutionException as e:
                on_predefined_tool_error(tool, e)
        else:
            resolved_tools.append(tool)

    tool_set.tools.clear()
    tool_set.tools.extend(resolved_tools)  # type: ignore[arg-type]

    return tool_set


def validate_toolset_dict_and_expand(
    raw: dict[str, Any],
    *,
    expand_fn: Callable[[ToolSet], ToolSet],
) -> ToolSet:
    """Parse ``raw`` as a ``ToolSet`` then apply ``expand_fn`` (typically ``resolve_toolset``)."""
    validated = _TOOLSET_ADAPTER.validate_python(raw)
    return expand_fn(validated)
