import logging
import re
from datetime import datetime, timezone

from aidial_client import DialException
from aidial_sdk.chat_completion import Attachment
from injector import inject

from quickapp.common.abstract.tool_call_result_processor import (
    ProcessingContext,
    ToolCallResultProcessor,
)
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.common.tool_names import (
    INTERNAL_FILE_READ_LINES_TOOL_NAME,
    INTERNAL_FILE_SEARCH_TOOL_NAME,
)
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_files_tooling._offload_config import ResolvedOffloadConfig
from quickapp.dial_files_tooling._utils import cap_output

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

        content_bytes = result.content.encode("utf-8")
        content_size = len(content_bytes)
        if content_size < self._config.size_threshold:
            return result

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S.%f")[:-3]
        safe_tool_name = re.sub(r"[_:]", "-", ctx.tool_name)
        filename = f"offloaded-responses/{safe_tool_name}-{timestamp}.txt"

        try:
            uploaded = await self._upload(content_bytes, filename, result.content_type)
        except Exception as e:
            logger.warning(
                "Failed to offload large response for tool '%s', truncating it instead",
                ctx.tool_name,
                exc_info=True,
            )
            return self._truncated_unsaved(result, ctx.tool_name, content_size, e)

        file_url = uploaded.url
        notice = (
            f"Response from '{ctx.tool_name}' was too large ({content_size} bytes) and\n"
            f"has been saved to: {file_url}\n"
            "Use one of (pass the saved URL above as `path`):\n"
            f"  - {INTERNAL_FILE_READ_LINES_TOOL_NAME}(path, start_line, end_line)\n"
            f"  - {INTERNAL_FILE_SEARCH_TOOL_NAME}"
            "(path, pattern, context_lines=0, case_insensitive=False)"
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

    async def _upload(
        self, content_bytes: bytes, filename: str, content_type: str | None
    ) -> Attachment:
        # `upload_bytes`, not `upload_attachment_to_core`: the latter swallows upload
        # errors, which would hide the reason from the model.
        file = await self._attachment_service.upload_bytes(
            data=content_bytes, content_type=content_type, filename=filename
        )
        return Attachment(title=filename, url=file.url, type=content_type or "text/plain")

    def _truncated_unsaved(
        self, result: ToolCallResult, tool_name: str, content_size: int, error: Exception
    ) -> ToolCallResult:
        """Bound an oversized response that could not be saved, so it cannot flood the context."""
        notice = (
            f"-- Response from '{tool_name}' was too large ({content_size} bytes) and could not "
            f"be saved to DIAL storage ({self._failure_reason(error)}); only the beginning is "
            "shown. Narrow the request to get less data. --"
        )
        room = max(self._config.size_threshold - len(notice), self._config.size_threshold // 2)
        capped, _ = cap_output(result.content, room)
        return result.model_copy(update={"content": f"{capped}\n{notice}"})

    @staticmethod
    def _failure_reason(error: Exception) -> str:
        # Status code or exception class only: error messages may carry URLs or headers.
        if isinstance(error, DialException):
            return f"HTTP {error.status_code}"
        return type(error).__name__
