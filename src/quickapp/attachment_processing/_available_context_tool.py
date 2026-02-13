import json
from typing import Any, Optional

from aidial_sdk.chat_completion import Message
from injector import AssistedBuilder, inject

from quickapp.attachment_processing._available_context_stage_wrapper import (
    _AvailableContextStageWrapper,
)
from quickapp.attachment_processing._context_entries import (
    AvailableContextToolResponse,
    build_context_entries,
    extract_seen_entries_from_messages,
)
from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.context import Context
from quickapp.config.tools.internal import InternalTool


@inject
class _AvailableContextTool(StagedBaseTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_AvailableContextStageWrapper],
        contexts: list[Context],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        messages: list[Message],
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            **kwargs,
        )
        self.__contexts: list[Context] = contexts
        self.__messages: list[Message] = messages

    def _get_response(self) -> AvailableContextToolResponse:
        """Collect context file metadata, flagging new or changed ones."""
        seen_entries = extract_seen_entries_from_messages(self.__messages)
        _, entries = build_context_entries(self.__contexts, seen_entries)
        return AvailableContextToolResponse(entries=entries)

    async def _run_in_stage_async(
        self,
        stage_wrapper: Optional[BaseStageWrapper] = None,
        *args: Any,
        **kwargs: Any,
    ) -> CompletionResult:
        response = self._get_response()
        content = json.dumps(response.model_dump(exclude_none=True), ensure_ascii=False)
        result = CompletionResult(content=content, content_type="application/json")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
