import base64
import logging
import re
from datetime import datetime, timezone

from aidial_sdk.chat_completion import Attachment
from injector import inject

from quickapp.common.abstract.tool_call_result_processor import (
    ProcessingContext,
    ToolCallResultProcessor,
)
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_files_tooling._offload_config import ResolvedOffloadConfig

logger = logging.getLogger(__name__)


@inject
class ToolCallResultOffloadProcessor(ToolCallResultProcessor):
    order = 0

    def __init__(
        self,
        config: ResolvedOffloadConfig,
        attachment_service: AttachmentService,
    ) -> None:
        self._config = config
        self._attachment_service = attachment_service

    async def process(self, result: ToolCallResult, ctx: ProcessingContext) -> ToolCallResult:
        if not self._config.enabled:
            return result
        if ctx.tool_name in self._config.excluded_tools:
            return result

        if len(result.content) < self._config.size_threshold:
            return result

        content_bytes = result.content.encode("utf-8")
        content_size = len(content_bytes)
        if content_size < self._config.size_threshold:
            return result

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S.%f")[:-3]
        safe_tool_name = re.sub(r"[_:]", "-", ctx.tool_name)
        filename = f"offloaded-responses/{safe_tool_name}-{timestamp}.txt"

        upload_attachment = Attachment(
            title=filename,
            data=base64.b64encode(content_bytes).decode(),
            type=result.content_type or "text/plain",
        )

        try:
            uploaded = await self._attachment_service.upload_attachment_to_core(upload_attachment)
            if uploaded.url is None:
                raise RuntimeError("Upload returned no URL")
        except Exception:
            logger.warning(
                "Failed to offload large response for tool '%s', returning original",
                ctx.tool_name,
                exc_info=True,
            )
            return result

        file_url = uploaded.url
        notice = (
            f"Response from '{ctx.tool_name}' was too large ({content_size} bytes) and\n"
            f"has been saved to: {file_url}\n"
            "Use one of (pass the saved URL above as `path`):\n"
            "  - internal_file_read_lines(path, start_line, end_line)\n"
            "  - internal_file_search(path, pattern, context_lines=0, case_insensitive=False)"
        )

        state = dict(result.state or {})
        state["offloaded_response"] = {
            "file_url": file_url,
            "original_size": content_size,
            "content_type": result.content_type,
        }

        uploaded.title = f"Offloaded response from '{ctx.tool_name}'"

        return ToolCallResult(
            tool_call_id=result.tool_call_id,
            content=notice,
            content_type="text/plain",
            attachments=[*(result.attachments or []), uploaded],
            state=state,
        )
