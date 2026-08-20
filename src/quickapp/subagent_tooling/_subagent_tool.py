from typing import Any

from injector import AssistedBuilder, inject

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.application import StageDisplayLevel
from quickapp.config.subagent import SubagentConfig
from quickapp.config.tools.internal import InternalTool

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
        subagents: list[SubagentConfig],
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
        self.__subagents = {s.name: s for s in subagents}

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        tool_call_id: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        subagent_type = kwargs.get("subagent_type")
        prompt = kwargs.get("prompt")

        subagent = self.__subagents.get(str(subagent_type))
        if subagent is None:
            raise InvalidToolCallParameterException(
                parameter_name="subagent_type",
                message=f"Unknown subagent '{subagent_type}'. Available: {sorted(self.__subagents)}",
            )
        if not prompt:
            raise InvalidToolCallParameterException(
                parameter_name="prompt", message="A task description is required."
            )

        answer = await self.__spawner.spawn(subagent, str(prompt))

        result = ToolCallResult(content=answer, content_type="text/markdown")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
