import logging

from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.tool_fallback import ContinueStrategyModel, ToolFallbackConfig
from quickapp.config.toolsets.dial_mcp import DialMCPToolSet
from quickapp.config.toolsets.mcp import MCPToolSet

logger = logging.getLogger(__name__)

# Dedupes already-logged (toolset, tool_or_none) pairs across requests so that a
# busy app with a static config only emits these INFO lines once per process.
_logged_keys: set[tuple[str, str | None]] = set()


def _has_customised_catch_all(fallback: ToolFallbackConfig) -> bool:
    return any(
        isinstance(s, ContinueStrategyModel) and s.trigger_on is None and s.instructions is not None
        for s in fallback.strategies
    )


def log_customised_catch_all_strategies(app_config: ApplicationConfig) -> None:
    """Log INFO for any `ContinueStrategyModel(trigger_on=None, instructions=...)`.

    These customisations no longer apply to `ToolTimeoutError` — the built-in
    timeout message takes over. See `docs/designs/configurable_timeouts.md` §7.
    """
    for tool_set in app_config.tool_sets:
        toolset_name = getattr(tool_set, "name", None) or type(tool_set).__name__

        if isinstance(tool_set, (MCPToolSet, DialMCPToolSet)):
            if _has_customised_catch_all(tool_set.fallback_configuration):
                key: tuple[str, str | None] = (toolset_name, None)
                if key not in _logged_keys:
                    _logged_keys.add(key)
                    logger.info(
                        "Toolset %r has a customised ContinueStrategyModel catch-all "
                        "(trigger_on=None, instructions=...); note that instructions on catch-all "
                        "strategies are deprecated and ignored — the tool error is forwarded to the LLM "
                        "directly. Also note that this strategy no longer applies to ToolTimeoutError.",
                        toolset_name,
                    )
            continue

        tools = getattr(tool_set, "tools", None)
        if not tools:
            continue
        for tool in tools:
            fallback = getattr(tool, "fallback_configuration", None)
            if fallback is None:
                continue
            if _has_customised_catch_all(fallback):
                open_ai_tool = getattr(tool, "open_ai_tool", None)
                tool_name = (
                    getattr(getattr(open_ai_tool, "function", None), "name", None)
                    or type(tool).__name__
                )
                key = (toolset_name, tool_name)
                if key not in _logged_keys:
                    _logged_keys.add(key)
                    logger.info(
                        "Tool %r in toolset %r has a customised ContinueStrategyModel "
                        "catch-all (trigger_on=None, instructions=...); note that instructions on "
                        "catch-all strategies are deprecated and ignored — the tool error is forwarded "
                        "to the LLM directly. Also note that this strategy no longer applies to ToolTimeoutError.",
                        tool_name,
                        toolset_name,
                    )
