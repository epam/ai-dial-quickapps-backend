import json
import mimetypes
from typing import Any, Optional

from injector import AssistedBuilder, inject

from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.context import Context, FileContextConfig
from quickapp.config.tools.internal import InternalTool
from quickapp.internal_tooling.attachment_notification_tooling._available_context_stage_wrapper import (
    _AvailableContextStageWrapper,
)


@inject
class _AvailableContextTool(StagedBaseTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_AvailableContextStageWrapper],
        contexts: list[Context],
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
        self.__contexts: list[Context] = contexts
        self.__seen_urls: set[str] = set()

    def collect_contexts(self) -> list[dict[str, str]]:
        """Collect context file metadata, flagging new or changed ones."""
        result: list[dict[str, str]] = []
        current_urls: set[str] = set()

        for ctx in self.__contexts:
            if not isinstance(ctx, FileContextConfig):
                continue
            url = ctx.url
            if url in current_urls:
                continue
            current_urls.add(url)
            title = url.rsplit("/", 1)[-1]
            mime_type = mimetypes.guess_type(title)[0] or ""
            entry: dict[str, str] = {
                "title": title,
                "url": url,
                "type": mime_type,
            }
            if ctx.description:
                entry["description"] = ctx.description
            if url not in self.__seen_urls:
                entry["status"] = "new"
            result.append(entry)

        self.__seen_urls = current_urls
        return result

    async def _run_in_stage_async(
        self,
        stage_wrapper: Optional[BaseStageWrapper] = None,
        *args: Any,
        **kwargs: Any,
    ) -> CompletionResult:
        contexts = self.collect_contexts()
        content = json.dumps(contexts, ensure_ascii=False)
        result = CompletionResult(content=content, content_type="application/json")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
