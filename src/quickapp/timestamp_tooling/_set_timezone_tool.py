from typing import Any, Optional
from zoneinfo import ZoneInfo

from injector import AssistedBuilder, inject

from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.message_metadata import USER_TIMEZONE_STATE_KEY
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.tools.internal import InternalTool
from quickapp.timestamp_tooling._set_timezone_stage_wrapper import _SetTimezoneStageWrapper


@inject
class _SetTimezoneTool(StagedBaseTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_SetTimezoneStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            **kwargs,
        )

    async def _run_in_stage_async(
        self,
        stage_wrapper: Optional[BaseStageWrapper] = None,
        *args: Any,
        **kwargs: Any,
    ) -> CompletionResult:
        timezone_input: str = kwargs.get("timezone", "")

        if timezone_input.lower() == "reset":
            result = CompletionResult(
                content="Timezone has been reset to server default.",
                content_type="text/plain",
                state={USER_TIMEZONE_STATE_KEY: None},
            )
        elif not self._is_valid_timezone(timezone_input):
            result = CompletionResult(
                content=f"Invalid timezone: '{timezone_input}'. "
                f"Please provide a valid IANA timezone name (e.g. 'America/New_York').",
                content_type="text/plain",
            )
        else:
            result = CompletionResult(
                content=f"Timezone set to {timezone_input}.",
                content_type="text/plain",
                state={USER_TIMEZONE_STATE_KEY: timezone_input},
            )

        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result

    @staticmethod
    def _is_valid_timezone(timezone_name: str) -> bool:
        try:
            ZoneInfo(timezone_name)
            return True
        except (KeyError, ValueError):
            return False
