import logging

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider, provider, singleton

from quickapp.common import StagedBaseTool
from quickapp.common.preview import preview_module
from quickapp.config.application import ApplicationConfig
from quickapp.config.subagent import SubagentsConfig

from ._manifest_compiler import selectable_tool_sets
from ._subagent_settings import SpawnSemaphore, SubagentSettings
from ._subagent_spawner import SubagentSpawner
from ._subagent_stage_wrapper import _SubagentStageWrapper
from ._subagent_tool import _SubagentTool
from ._tool_config import TASK_TOOL_NAME, build_spawn_tool_config

logger = logging.getLogger(__name__)


@preview_module
class SubagentToolingModule(Module):
    """In-process subagent spawning."""

    def configure(self, binder: Binder) -> None:
        binder.bind(SubagentSettings, to=SubagentSettings, scope=singleton)
        # Singleton: the spawn cap bounds this replica's event loop, so it has to hold
        # across concurrent user requests, not per request.
        binder.bind(SpawnSemaphore, to=SpawnSemaphore, scope=singleton)
        binder.bind(SubagentSpawner, to=SubagentSpawner, scope=request_scope)
        binder.bind(_SubagentStageWrapper, to=_SubagentStageWrapper)
        logger.debug("SubagentTooling module configuration completed")

    @provider
    def _provide_subagents_config(self, app_config: ApplicationConfig) -> SubagentsConfig:
        """The app's subagent settings, or all-defaults when the section is absent.

        The defaults are only ever reached by injection sites that exist regardless of
        the feature switch; nothing spawns unless `_provide_subagent_tools` offered the
        tool, and that checks `enabled` first.
        """
        features = app_config.features
        return (features.subagents if features else None) or SubagentsConfig()

    @multiprovider
    def _provide_subagent_tools(
        self,
        app_config: ApplicationConfig,
        config: SubagentsConfig,
        tool_builder: AssistedBuilder[_SubagentTool],
    ) -> list[StagedBaseTool]:
        """The `task` tool, when this app opted into delegation.

        Its schema is built here rather than at import time because the `tool_sets` enum
        is drawn from this app's own tool sets — the coordinator picks from them per
        spawn, so it needs to see them by name.
        """
        if not config.enabled:
            return []
        return [
            tool_builder.build(
                tool_config=build_spawn_tool_config(selectable_tool_sets(app_config)),
                name=TASK_TOOL_NAME,
            )
        ]
