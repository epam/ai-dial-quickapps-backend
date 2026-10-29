from typing import Any
from zoneinfo import ZoneInfo

from injector import AssistedBuilder, inject

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.iana_timezones import is_valid_iana_timezone, normalize_timezone_name
from quickapp.common.message_metadata import (
    MessageMetadata,
    TimestampMetadata,
    TimestampSource,
    set_metadata_in_state,
)
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.time_provider import TimeProvider
from quickapp.config.application import StageDisplayLevel
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
        raw_timezone = kwargs.get("timezone")
        if raw_timezone is not None and not isinstance(raw_timezone, str):
            raise InvalidToolCallParameterException(
                "timezone", "Must be a string IANA time zone name like 'Europe/Warsaw'."
            )
        timezone_str = normalize_timezone_name(raw_timezone)

        source: TimestampSource | None
        if timezone_str is not None:
            if not is_valid_iana_timezone(timezone_str):
                raise InvalidToolCallParameterException(
                    "timezone",
                    f"Unknown IANA time zone '{timezone_str}'. "
                    "Use a name like 'Europe/Warsaw' or 'Asia/Tokyo'.",
                )
            tz = ZoneInfo(timezone_str)
            now = self.__time_provider.now().astimezone(tz)
            # The model chose this zone; its call arguments already say so, no source label.
            source = None
            content = f"{now.isoformat()} ({tz})"
        else:
            tz = self.__time_provider.tz
            now = self.__time_provider.now()
            source = self.__time_provider.source
            content = self.__time_provider.format_timestamp(now)
        tz_name = str(tz)

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
