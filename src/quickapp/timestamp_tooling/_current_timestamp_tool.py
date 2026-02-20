from typing import Any, Optional

from injector import AssistedBuilder, inject

from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.message_metadata import MessageMetadata
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.time_provider import TimeProvider
from quickapp.config.tools.internal import InternalTool
from quickapp.timestamp_tooling._current_timestamp_stage_wrapper import (
    _CurrentTimestampStageWrapper,
)


@inject
class _CurrentTimestampTool(StagedBaseTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_CurrentTimestampStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        time_provider: TimeProvider,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            **kwargs,
        )
        self.__time_provider = time_provider

    async def _run_in_stage_async(
        self,
        stage_wrapper: Optional[BaseStageWrapper] = None,
        *args: Any,
        **kwargs: Any,
    ) -> CompletionResult:
        now = self.__time_provider.now()
        tz_name = self.__time_provider.tz_name
        source = self.__time_provider.source

        metadata = MessageMetadata(
            response_timestamp=now,
            timestamp_source=source,
            timezone_name=tz_name,
        )

        content = f"{now.isoformat()} ({tz_name}, source={source.value})"
        result = CompletionResult(
            content=content,
            content_type="text/plain",
            state=metadata.to_state_entry(),
        )
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
