import json
from typing import Any, Optional

from injector import AssistedBuilder, inject

from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.context import Context
from quickapp.config.tools.internal import InternalTool
from quickapp.internal_tooling.attachment_notification_tooling._available_context_stage_wrapper import (
    _AvailableContextStageWrapper,
)
from quickapp.internal_tooling.attachment_notification_tooling._context_entries import (
    ContextEntry,
    build_context_entries,
    extract_seen_entries_from_messages,
)


@inject
class _AvailableContextTool(StagedBaseTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_AvailableContextStageWrapper],
        contexts: list[Context],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        messages_context: MessagesMixin,
        name: str = "",
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            **kwargs,
        )
        self.__contexts: list[Context] = contexts
        self.__messages_context: MessagesMixin = messages_context

    def collect_contexts(self) -> list[ContextEntry]:
        """Collect context file metadata, flagging new or changed ones."""
        seen_entries = extract_seen_entries_from_messages(self.__messages_context.messages)
        _, entries = build_context_entries(self.__contexts, seen_entries)
        return entries

    async def _run_in_stage_async(
        self,
        stage_wrapper: Optional[BaseStageWrapper] = None,
        *args: Any,
        **kwargs: Any,
    ) -> CompletionResult:
        contexts = self.collect_contexts()
        content = json.dumps(
            [e.model_dump(exclude_none=True) for e in contexts], ensure_ascii=False
        )
        result = CompletionResult(content=content, content_type="application/json")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
