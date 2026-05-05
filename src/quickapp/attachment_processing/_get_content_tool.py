"""
Lazy-load a single allowed attachment by URL.

Whitelist rule (defense in depth; see product design): success only if the tool argument,
after :func:`normalize_attachment_url_argument`, equals one of request-allowed URLs:
  - admin file contexts accepted by orchestrator deployment
  - user message attachments accepted by orchestrator deployment
No prefix-only or traversal matches — membership in the allowed set only.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aidial_sdk.chat_completion import Attachment
from injector import AssistedBuilder, inject

from quickapp.attachment_processing._get_content_stage_wrapper import _GetContentStageWrapper
from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.attachment_processing_utils import (
    attachment_mime_type,
    collect_get_content_allowed_urls,
    inferred_mime_type_for_file_context_url,
    normalize_attachment_url_argument,
    user_attachments_from_messages,
)
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.stage_close_registry import DeferredStageCloseRegistry
from quickapp.common.utils import posix_path_last_segment
from quickapp.config.context import Context, FileContextConfig
from quickapp.config.tools.internal import InternalTool
from quickapp.dial_core_services.orchestrator_deployment_capabilities import (
    OrchestratorCapabilities,
)

logger = logging.getLogger(__name__)


def _configured_file_context_by_url(
    contexts: list[Context], argument_url: str
) -> FileContextConfig | None:
    normalized_arg = normalize_attachment_url_argument(argument_url)
    for ctx in contexts:
        if not isinstance(ctx, FileContextConfig):
            continue
        if normalize_attachment_url_argument(ctx.url) == normalized_arg:
            return ctx
    return None


@inject
class _GetContentTool(StagedBaseTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_GetContentStageWrapper],
        contexts: list[Context],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        orchestrator_capabilities: OrchestratorCapabilities,
        messages_mixin: MessagesMixin,
        deferred_stage_close_registry: DeferredStageCloseRegistry,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            deferred_stage_close_registry=deferred_stage_close_registry,
            argument_transformers=argument_transformers,
            **kwargs,
        )
        self.__contexts: list[Context] = contexts
        self.__messages_mixin: MessagesMixin = messages_mixin
        self.__orchestrator_capabilities: OrchestratorCapabilities = orchestrator_capabilities
        self.__stage_close_registry: DeferredStageCloseRegistry = deferred_stage_close_registry

    def _error_result(self, message: str) -> ToolCallResult:
        payload = json.dumps({"ok": False, "error": message}, ensure_ascii=False)
        return ToolCallResult(content=payload, content_type="application/json")

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        attachment_url: str | None = None,
        context_url: str | None = None,
        *args: Any,
        tool_call_id: str | None = None,
        **kwargs: Any,
    ) -> ToolCallResult:
        raw_url = attachment_url if attachment_url is not None else context_url
        if raw_url is None or not str(raw_url).strip():
            logger.info("get_content tool rejected: empty attachment_url")
            return self._error_result("Missing or empty attachment_url.")

        normalized_url = normalize_attachment_url_argument(str(raw_url))
        allowed_urls = collect_get_content_allowed_urls(
            contexts=self.__contexts,
            messages=self.__messages_mixin.messages,
            input_attachment_types=self.__orchestrator_capabilities.input_attachment_types,
        )
        if normalized_url not in allowed_urls:
            log_segment = posix_path_last_segment(raw_url)
            logger.info(
                "get_content tool rejected: URL not in allowed admin/user attachments (path_tail=%s)",
                log_segment,
            )
            return self._error_result(
                "Unknown or disallowed attachment_url; use exact admin context or user attachment url."
            )

        if not normalized_url.startswith("files/"):
            logger.info("get_content tool rejected: URL does not start with files/")
            return self._error_result("Invalid storage path for attachment file.")

        matched_context = _configured_file_context_by_url(self.__contexts, normalized_url)
        matched_user_attachment = None
        for user_attachment in user_attachments_from_messages(self.__messages_mixin.messages):
            if (
                user_attachment.url
                and normalize_attachment_url_argument(str(user_attachment.url)) == normalized_url
            ):
                matched_user_attachment = user_attachment
                break

        if matched_context is not None:
            mime = inferred_mime_type_for_file_context_url(matched_context.url)
            title = matched_context.url.rsplit("/", 1)[-1]
        elif matched_user_attachment is not None:
            mime = attachment_mime_type(matched_user_attachment)
            if matched_user_attachment.title:
                title = str(matched_user_attachment.title)
            else:
                title = normalized_url.rsplit("/", 1)[-1]
        else:
            logger.info("get_content tool rejected: URL not found in request messages/config")
            return self._error_result("Attachment URL is not available in this request.")

        if not self.__orchestrator_capabilities.orchestrator_accepts_mime_type(mime):
            logger.info(
                "get_content tool rejected: orchestrator does not accept MIME %s for deployment id=%s",
                mime,
                self.__orchestrator_capabilities.deployment_id,
            )
            return self._error_result("Orchestrator deployment does not accept this file type.")

        attachment = Attachment(
            title=title, type=mime or "application/octet-stream", url=normalized_url
        )
        payload = json.dumps(
            {"ok": True, "url": normalized_url, "title": title, "type": attachment.type},
            ensure_ascii=False,
        )
        result = ToolCallResult(
            content=payload,
            content_type="application/json",
            attachments=[attachment],
        )
        logger.debug(
            "get_content tool allowed: deployment_id=%s url_basename=%s type=%s",
            self.__orchestrator_capabilities.deployment_id,
            title,
            attachment.type,
        )
        if stage_wrapper:
            if isinstance(self._tool_config, InternalTool) and self._tool_config.defer_stage_close:
                assert tool_call_id is not None
                sw = stage_wrapper
                res = result

                def apply_success_to_stage() -> None:
                    sw.add_result(res)

                self.__stage_close_registry.register_stage_ui_before_close(
                    stage_wrapper,
                    apply_success_to_stage,
                    tool_call_id=tool_call_id,
                )
            else:
                stage_wrapper.add_result(result)
        return result
