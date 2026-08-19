import logging

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider

from quickapp.common import StagedBaseTool
from quickapp.common.exceptions import InitializationException, ToolInitializationException
from quickapp.common.preview import preview_module
from quickapp.config.application import ApplicationConfig
from quickapp.config.subagent import SubagentConfig

from ._subagent_spawner import SubagentSpawner
from ._subagent_stage_wrapper import _SubagentStageWrapper
from ._subagent_tool import _SubagentTool
from ._tool_config import SPAWN_TOOL_NAME, build_spawn_tool_config

logger = logging.getLogger(__name__)


@preview_module
class SubagentToolingModule(Module):
    """In-process subagent spawning."""

    def configure(self, binder: Binder) -> None:
        binder.bind(SubagentSpawner, to=SubagentSpawner, scope=request_scope)
        binder.bind(_SubagentStageWrapper, to=_SubagentStageWrapper)
        logger.debug("SubagentTooling module configuration completed")

    @multiprovider
    def _provide_subagents(self, app_config: ApplicationConfig) -> list[SubagentConfig]:
        return list(app_config.subagents or [])

    @multiprovider
    def _provide_initialization_exceptions(
        self, app_config: ApplicationConfig
    ) -> list[InitializationException]:
        """Surface dangling `tool_sets` references before the LLM can spawn.

        Caught here, the app builder sees a named bad reference. Caught at spawn
        time, they see a subagent that answered without tools.
        """
        available = {ts.name for ts in app_config.tool_sets}
        exceptions: list[InitializationException] = []
        for subagent in app_config.subagents or []:
            unknown = sorted(set(subagent.tool_sets or []) - available)
            if unknown:
                exceptions.append(
                    ToolInitializationException(
                        message=(
                            f"Subagent '{subagent.name}' references tool sets that do not exist "
                            f"in this app: {unknown}. Available: {sorted(available) or '(none)'}."
                        ),
                        tool_name=SPAWN_TOOL_NAME,
                    )
                )
        return exceptions

    @multiprovider
    def _provide_subagent_tools(
        self,
        subagents: list[SubagentConfig],
        tool_builder: AssistedBuilder[_SubagentTool],
    ) -> list[StagedBaseTool]:
        if not subagents:
            return []
        return [
            tool_builder.build(
                tool_config=build_spawn_tool_config(subagents),
                name=SPAWN_TOOL_NAME,
            )
        ]
