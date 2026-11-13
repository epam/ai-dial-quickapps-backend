import logging

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider, provider, singleton

from quickapp.common import StagedBaseTool
from quickapp.common.preview import preview_module
from quickapp.config.application import ApplicationConfig
from quickapp.config.run_task import RunTaskConfig

from ._run_task_settings import RunTaskSettings
from ._run_task_tool import _RunTaskTool
from ._task_runner import TaskRunner
from ._task_semaphore import TaskSemaphore
from ._task_stage_wrapper import _TaskStageWrapper
from ._tool_catalogue import _DelegableToolNames
from ._tool_config import RUN_TASK_TOOL_CONFIG

logger = logging.getLogger(__name__)


@preview_module
class TaskToolingModule(Module):
    """The built-in ``internal_run_task`` tool: delegated tasks run in-process."""

    def configure(self, binder: Binder) -> None:
        binder.bind(RunTaskSettings, to=RunTaskSettings, scope=singleton)
        # Singleton: the cap bounds this replica, across concurrent user requests.
        binder.bind(TaskSemaphore, to=TaskSemaphore, scope=singleton)
        binder.bind(TaskRunner, to=TaskRunner, scope=request_scope)
        binder.bind(_DelegableToolNames, to=_DelegableToolNames, scope=request_scope)
        binder.bind(_TaskStageWrapper, to=_TaskStageWrapper)
        logger.debug("TaskTooling module configuration completed")

    @provider
    def _provide_run_task_config(self, app_config: ApplicationConfig) -> RunTaskConfig:
        features = app_config.features
        return (features.run_task if features else None) or RunTaskConfig()

    @multiprovider
    def _provide_run_task_tools(
        self,
        config: RunTaskConfig,
        tool_builder: AssistedBuilder[_RunTaskTool],
    ) -> list[StagedBaseTool]:
        if not config.enabled:
            return []
        # No argument transformers: resolving a `file:` reference would paste the file
        # into the prompt. The task reads files itself through the attachment readers.
        return [
            tool_builder.build(
                tool_config=RUN_TASK_TOOL_CONFIG,
                name=RUN_TASK_TOOL_CONFIG.open_ai_tool.function.name,
                description=RUN_TASK_TOOL_CONFIG.open_ai_tool.function.description,
            )
        ]
