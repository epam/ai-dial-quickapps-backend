import asyncio
import logging

from injector import ProviderOf, inject

from quickapp.agent_hooks._handlers import HookHandlerRegistry, hook_display_name
from quickapp.common.hook_context.context import HookContext, HookResult
from quickapp.config.application import ApplicationConfig
from quickapp.config.hooks import HookConfig, HookEvent

logger = logging.getLogger(__name__)

_EVENT_DEFAULT_TIMEOUT: dict[HookEvent, float] = {
    HookEvent.ON_REQUEST_START: 15.0,
    HookEvent.ON_COMPLETION: 30.0,
}


def _resolve_timeout(hook: HookConfig) -> float:
    if hook.timeout_seconds is not None:
        return hook.timeout_seconds
    return _EVENT_DEFAULT_TIMEOUT[hook.event]


@inject
class HookDispatcher:
    """Runs configured hooks with a per-event timeout and never lets one fail the request."""

    def __init__(
        self,
        app_config_provider: ProviderOf[ApplicationConfig],
        registry: HookHandlerRegistry,
    ) -> None:
        self._app_config_provider = app_config_provider
        self._registry = registry

    async def run_hook(self, hook: HookConfig, context: HookContext) -> HookResult | None:
        name = hook_display_name(hook)
        timeout = _resolve_timeout(hook)
        try:
            handler = self._registry.handler_for(hook)
            return await asyncio.wait_for(handler.run(context), timeout)
        except TimeoutError:
            logger.warning(
                "Hook %r timed out (event=%s, timeout=%ss) - skipping",
                name,
                hook.event.value,
                timeout,
            )
            return None
        except Exception:
            logger.exception("Hook %r failed (event=%s) - skipping", name, hook.event.value)
            return None

    async def dispatch(self, event: HookEvent, context: HookContext) -> list[HookResult]:
        results: list[HookResult] = []
        for hook in self._app_config_provider.get().hooks or []:
            if hook.event != event:
                continue
            result = await self.run_hook(hook, context)
            if result is not None:
                results.append(result)
        return results
