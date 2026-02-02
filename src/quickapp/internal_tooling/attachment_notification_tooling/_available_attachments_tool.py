import json
from typing import Any, Optional

from aidial_sdk.chat_completion.request import Role
from injector import AssistedBuilder, inject

from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.tools.internal import InternalTool
from quickapp.internal_tooling.attachment_notification_tooling._available_attachments_stage_wrapper import (
    _AvailableAttachmentsStageWrapper,
)


@inject
class _AvailableAttachmentsTool(StagedBaseTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_AvailableAttachmentsStageWrapper],
        messages_context: MessagesMixin,
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
        self.__messages_context: MessagesMixin = messages_context
        self.__seen_urls: set[str] = set()

    def collect_attachments(self) -> list[dict[str, str]]:
        """Collect attachment metadata from all USER messages, flagging new ones."""
        result: list[dict[str, str]] = []
        current_urls: set[str] = set()

        for message in self.__messages_context.messages:
            if message.role != Role.USER:
                continue
            if not message.custom_content or not message.custom_content.attachments:
                continue
            for attachment in message.custom_content.attachments:
                url = str(attachment.url) if attachment.url else ""
                if not url or url in current_urls:
                    continue
                current_urls.add(url)
                entry: dict[str, str] = {
                    "title": str(attachment.title) if attachment.title else "",
                    "url": url,
                    "type": str(attachment.type) if attachment.type else "",
                }
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
        attachments = self.collect_attachments()
        content = json.dumps(attachments, ensure_ascii=False)
        result = CompletionResult(content=content, content_type="application/json")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
