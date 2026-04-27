"""
Lazy-load a single admin-configured file context by URL.

Whitelist rule (defense in depth; see product design): success only if the tool argument,
after :func:`normalize_context_url_argument`, equals ``FileContextConfig.url`` stripped for some
context entry in the current ``ApplicationConfig.contexts``. No prefix-only or traversal
matches—membership in the configured set only.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aidial_sdk.chat_completion import Attachment
from injector import AssistedBuilder, inject

from quickapp.agent.orchestrator_deployment_capabilities import OrchestratorDeploymentCapabilities
from quickapp.attachment_processing._context_entries import (
    inferred_mime_type_for_file_context_url,
    normalize_context_url_argument,
)
from quickapp.attachment_processing._get_context_stage_wrapper import _GetContextStageWrapper
from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.utils import posix_path_last_segment
from quickapp.config.context import Context, FileContextConfig
from quickapp.config.tools.internal import InternalTool

logger = logging.getLogger(__name__)


def _configured_file_context_by_url(
    contexts: list[Context], argument_url: str
) -> FileContextConfig | None:
    normalized_arg = normalize_context_url_argument(argument_url)
    for ctx in contexts:
        if not isinstance(ctx, FileContextConfig):
            continue
        if ctx.url.strip() == normalized_arg:
            return ctx
    return None


@inject
class _GetContextTool(StagedBaseTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_GetContextStageWrapper],
        contexts: list[Context],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        orchestrator_capabilities: OrchestratorDeploymentCapabilities,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            argument_transformers=argument_transformers,
            **kwargs,
        )
        self.__contexts: list[Context] = contexts
        self.__orchestrator_capabilities: OrchestratorDeploymentCapabilities = (
            orchestrator_capabilities
        )

    def _error_result(self, message: str) -> ToolCallResult:
        payload = json.dumps({"ok": False, "error": message}, ensure_ascii=False)
        return ToolCallResult(content=payload, content_type="application/json")

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        context_url: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        if context_url is None or not str(context_url).strip():
            logger.info("get_content tool rejected: empty context_url")
            return self._error_result("Missing or empty context_url.")

        raw_url = str(context_url)
        matched = _configured_file_context_by_url(self.__contexts, raw_url)
        if matched is None:
            log_segment = posix_path_last_segment(raw_url)
            logger.info(
                "get_content tool rejected: URL not in configured contexts (path_tail=%s)",
                log_segment,
            )
            return self._error_result("Unknown or disallowed context_url; use exact url from list.")

        if not raw_url.strip().startswith("files/"):
            logger.info("get_content tool rejected: URL does not start with files/")
            return self._error_result("Invalid storage path for context file.")

        mime = inferred_mime_type_for_file_context_url(matched.url)
        if not self.__orchestrator_capabilities.orchestrator_accepts_mime_type(mime):
            logger.info(
                "get_content tool rejected: orchestrator does not accept MIME %s for deployment id=%s",
                mime,
                self.__orchestrator_capabilities.deployment_id,
            )
            return self._error_result("Orchestrator deployment does not accept this file type.")

        title = matched.url.rsplit("/", 1)[-1]
        attachment = Attachment(
            title=title, type=mime or "application/octet-stream", url=matched.url
        )
        payload = json.dumps(
            {"ok": True, "url": matched.url, "title": title, "type": attachment.type},
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
            stage_wrapper.add_result(result)
        return result
