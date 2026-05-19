from typing import Any
from zoneinfo import ZoneInfo

from injector import AssistedBuilder, inject

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.message_metadata import (
    MessageMetadata,
    TimestampMetadata,
    TimestampSource,
    set_metadata_in_state,
)
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.application import StageDisplayLevel
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
        stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            stage_display_level=stage_display_level,
            argument_transformers=argument_transformers,
            **kwargs,
        )
        self.__time_provider = time_provider

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        tool_call_id: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        timezone_str: str | None = kwargs.get("timezone")

        if timezone_str is not None:
            tz = ZoneInfo(timezone_str)
            source = TimestampSource.REQUEST
        else:
            tz = self.__time_provider.tz
            source = self.__time_provider.source

        now = self.__time_provider.now().astimezone(tz)
        tz_name = str(tz)

        content = f"{now.isoformat()} ({tz_name}, source={source.value})"

        state: dict[str, Any] = {}
        set_metadata_in_state(
            state,
            MessageMetadata(
                timestamp=TimestampMetadata(
                    response_timestamp=now,
                    timestamp_source=source,
                    timezone_name=tz_name,
                )
            ),
        )

        result = ToolCallResult(content=content, content_type="text/plain", state=state)
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
