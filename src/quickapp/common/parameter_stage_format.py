"""Shared markdown formatting for tool parameters shown in stages."""

from __future__ import annotations

from typing import Any

from quickapp.common.utils import fenced_code_block
from quickapp.config.tools.base import BaseOpenAITool, BaseTool
from quickapp.config.tools.display.paramenter import (
    FormattedParameterConfig,
    ParameterDisplayConfig,
)


def extract_parameters_config_map(
    tool_config: BaseTool | None,
) -> dict[str, FormattedParameterConfig]:
    """Build param-name → stage display config from an OpenAI tool schema."""
    result: dict[str, FormattedParameterConfig] = {}
    if not isinstance(tool_config, BaseOpenAITool):
        return result
    for prop_name, config in tool_config.open_ai_tool.function.parameters.properties.items():
        display_conf: ParameterDisplayConfig = config.display
        if display_conf and display_conf.stage:
            result[prop_name] = display_conf.stage
    return result


def resolve_tool_stage_display_name(
    tool_config: BaseTool | None,
    stage_name_component: str | None = None,
) -> str | None:
    """Resolve the stage title used for a tool (config display name / fallbacks)."""
    if tool_config is None:
        return stage_name_component
    display = tool_config.display
    if display and display.stage and display.stage.show and display.stage.name:
        return display.stage.name
    if stage_name_component:
        return stage_name_component
    if isinstance(tool_config, BaseOpenAITool):
        return f"Calling {tool_config.open_ai_tool.function.name} application"
    return None


def parameter_name_markdown(param_name: str, display_config: FormattedParameterConfig) -> str:
    if display_config.name:
        return display_config.name
    if display_config.ignore_parameter_name:
        return ""
    return f"***{param_name}:*** "


def parameter_value_prefix(display_config: FormattedParameterConfig) -> str:
    return display_config.prefix if display_config.prefix else ""


def parameter_value_suffix(display_config: FormattedParameterConfig) -> str:
    return display_config.suffix if display_config.suffix else ""


def format_parameter_value(param_value: Any, display_config: FormattedParameterConfig) -> str:
    result_value: Any = (
        display_config.replaced_value_info if display_config.replaced_value_info else param_value
    )
    if display_config.format is not None:
        block = fenced_code_block(str(result_value), display_config.format)
        result_value = f"\n{block}\n"
    return str(result_value)


def order_parameters(
    parameters: dict[str, Any],
    parameters_config_map: dict[str, FormattedParameterConfig],
) -> dict[str, Any]:
    def _order(param_name: str) -> int:
        display_config = parameters_config_map.get(param_name)
        return display_config.order if display_config else 0

    return dict(sorted(parameters.items(), key=lambda item: _order(item[0])))


def render_config_map_parameters(
    parameters: dict[str, Any],
    parameters_config_map: dict[str, FormattedParameterConfig],
) -> str:
    """Render parameters using the per-parameter display config map (static dump)."""
    stage_params = "> #### Request:\n\r"
    for param_name, param_value in order_parameters(parameters, parameters_config_map).items():
        if display_config := parameters_config_map.get(param_name):
            if not display_config.ignore:
                stage_params += parameter_name_markdown(param_name, display_config)
                stage_params += parameter_value_prefix(display_config)
                stage_params += format_parameter_value(param_value, display_config)
                stage_params += parameter_value_suffix(display_config)
                stage_params += "\n\r"
        else:
            stage_params += f"***{param_name}:*** {param_value}\n\r"
    return stage_params


def streaming_fence_open(language: str) -> str:
    """Open a fenced block for incremental streaming (fixed 4-backtick fence)."""
    return f"````{language}\n"


def streaming_fence_close() -> str:
    return "\n````"
