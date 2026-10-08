import logging
from abc import ABC, abstractmethod

from injector import inject

from quickapp.agent_hooks._hook_tool_registry import HookToolRegistry
from quickapp.common.hook_context.context import HookContext, HookResult
from quickapp.common.hook_context.templating import TemplateResolutionError, render_arguments
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.common.synthetic_injection.staged_tool_lookup import (
    build_staged_tool_index,
    find_staged_tool,
)
from quickapp.common.utils import sanitize_toolname
from quickapp.config.application import StageDisplayLevel
from quickapp.config.hooks import HookConfig, ToolCallHookConfig

logger = logging.getLogger(__name__)

_PROBE_CALL_ID = "synthetic_injection_probe"


def resolve_hook_tool_name(config: ToolCallHookConfig) -> str:
    if config.toolset_name is not None:
        return sanitize_toolname(f"{config.toolset_name}_{config.tool_name}")
    return config.tool_name


def hook_display_name(config: ToolCallHookConfig) -> str:
    return config.name or config.tool_name


class HookHandler(ABC):
    """Does the work of one configured hook. Failure policy belongs to the dispatcher."""

    @abstractmethod
    async def run(self, context: HookContext) -> HookResult | None: ...


class ToolCallHookHandler(HookHandler):
    def __init__(self, config: ToolCallHookConfig, tools: list[StagedBaseTool]) -> None:
        self._config = config
        self._tools = build_staged_tool_index(tools)

    async def run(self, context: HookContext) -> HookResult | None:
        hook_name = hook_display_name(self._config)
        try:
            rendered = render_arguments(self._config.arguments, context)
        except TemplateResolutionError as error:
            logger.warning("Hook %r skipped: %s", hook_name, error)
            return None

        tool_name = resolve_hook_tool_name(self._config)
        tool = find_staged_tool(self._tools, tool_name, logger, "ToolCallHookHandler")
        if tool is None:
            return None

        result = await tool.arun(_PROBE_CALL_ID, stage_level=StageDisplayLevel.DEBUG, **rendered)
        return HookResult(
            hook_name=hook_name,
            content=result.content,
            tool_name=tool_name,
            arguments=rendered,
        )


@inject
class HookHandlerRegistry:
    """Builds one handler per configured hook, lazily, and reuses it for the request."""

    def __init__(self, tool_registry: HookToolRegistry) -> None:
        self._tool_registry = tool_registry
        self._handlers: dict[int, HookHandler] = {}

    def handler_for(self, hook: HookConfig) -> HookHandler:
        key = id(hook)
        handler = self._handlers.get(key)
        if handler is None:
            handler = self._build(hook)
            self._handlers[key] = handler
        return handler

    def _build(self, hook: HookConfig) -> HookHandler:
        match hook:
            case ToolCallHookConfig():
                return ToolCallHookHandler(hook, self._tool_registry.tools)
