import base64
import logging
from datetime import datetime, timezone

from aidial_sdk.chat_completion import Attachment
from injector import inject

from quickapp.common.abstract.tool_call_result_processor import (
    ProcessingContext,
    ToolCallResultProcessor,
)
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.config.application import ApplicationConfig
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.tool_call_result_offload._settings import ToolCallResultOffloadSettings

logger = logging.getLogger(__name__)


@inject
class LargeResponseProcessor(ToolCallResultProcessor):
    priority = 100

    def __init__(
        self,
        settings: ToolCallResultOffloadSettings,
        attachment_service: AttachmentService,
        app_config: ApplicationConfig,
    ) -> None:
        self._settings = settings
        self._attachment_service = attachment_service
        self._app_config = app_config

    async def process(self, result: ToolCallResult, ctx: ProcessingContext) -> ToolCallResult:
        if not self._settings.enabled:
            return result
        if ctx.tool_name in self._settings.excluded_tools:
            return result

        app_offload_config = self._app_config.tool_defaults.tool_call_result_offload
        threshold = (
            app_offload_config.size_threshold
            if app_offload_config is not None
            else self._settings.size_threshold
        )
        content_bytes = result.content.encode("utf-8")
        if len(content_bytes) < threshold:
            return result

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        filename = f"offloaded-responses/{ctx.tool_name}-{timestamp}.txt"

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
            f"Response from '{ctx.tool_name}' was too large ({len(content_bytes)} chars) and\n"
            f"has been saved to: {file_url}\n"
            "Use one of:\n"
            "  - read_file_lines(file_url, start_line, end_line)\n"
            "  - search_in_file(file_url, pattern, context_lines=0, case_insensitive=False)"
        )

        state = dict(result.state or {})
        state["offloaded_response"] = {
            "file_url": file_url,
            "original_size": len(content_bytes),
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
