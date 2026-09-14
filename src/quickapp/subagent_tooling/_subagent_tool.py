from typing import Any

from injector import AssistedBuilder, inject

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.application import ApplicationConfig, StageDisplayLevel
from quickapp.config.tools.internal import InternalTool

from ._manifest_compiler import tool_set_names
from ._subagent_spawner import SubagentSpawner
from ._subagent_stage_wrapper import _SubagentStageWrapper


@inject
class _SubagentTool(StagedBaseTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_SubagentStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        spawner: SubagentSpawner,
        app_config: ApplicationConfig,
        stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            stage_display_level=stage_display_level,
            **kwargs,
        )
        self.__spawner = spawner
        self.__available_tool_sets = tool_set_names(app_config)

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        tool_call_id: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        prompt = kwargs.get("prompt")
        if not prompt:
            raise InvalidToolCallParameterException(
                parameter_name="prompt", message="A task description is required."
            )

        tool_sets = self.__validated_tool_sets(kwargs.get("tool_sets"))
        spawned = await self.__spawner.spawn(str(prompt), tool_sets, stage_wrapper)

        result = ToolCallResult(
            content=spawned.answer,
            content_type="text/markdown",
            attachments=spawned.attachments or None,
        )
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result

    def __validated_tool_sets(self, requested: Any) -> list[str]:
        """The tool sets this spawn asked for, every one of them known to the app.

        Unknown names fail the whole call rather than being dropped: a spoke quietly
        running with fewer tools than the coordinator intended does not error, it
        answers from the prompt alone. The message names the valid options so the LLM
        can retry correctly.
        """
        if requested is None:
            raise InvalidToolCallParameterException(
                parameter_name="tool_sets",
                message=(
                    "A list of tool sets is required. Pass [] for a subagent that only "
                    f"reasons. Available: {self.__available_tool_sets or '(none)'}."
                ),
            )
        if not isinstance(requested, list) or not all(isinstance(name, str) for name in requested):
            raise InvalidToolCallParameterException(
                parameter_name="tool_sets", message="Expected a list of tool set names."
            )

        unknown = [name for name in requested if name not in self.__available_tool_sets]
        if unknown:
            raise InvalidToolCallParameterException(
                parameter_name="tool_sets",
                message=(
                    f"Unknown tool sets: {unknown}. "
                    f"Available: {self.__available_tool_sets or '(none)'}."
                ),
            )
        return list(requested)
