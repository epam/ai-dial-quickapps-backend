"""Lazy-load a single attachment by url for the current turn.

External ``http(s)`` urls are promoted to a durable DIAL file via
``_AttachmentMaterializer``; DIAL ``files/`` urls pass through. Authorization of the
underlying fetch is enforced upstream — DIAL Core gates ``files/`` access by the
caller's bucket permissions, and the external-fetch policy gates ``http(s)``.
"""

import logging
from typing import Any

from aidial_sdk.chat_completion import Attachment
from injector import AssistedBuilder, inject
from pydantic import BaseModel, ConfigDict

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.attachment_processing_utils import (
    attachment_mime_type,
    inferred_mime_type_for_file_context_url,
    normalize_attachment_url_argument,
    user_attachments_from_messages,
)
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.stage_close_registry import DeferredStageCloseRegistry
from quickapp.common.url_classification import UrlScheme
from quickapp.config.application import StageDisplayLevel
from quickapp.config.tools.internal import InternalTool
from quickapp.core.agent import OrchestratorCapabilities
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._attachment_materializer import (
    _AttachmentMaterializer,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_stage_wrapper import (
    _GetContentStageWrapper,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_tool_response import (
    build_tool_result_parts,
    fail_response,
    success_response,
)

logger = logging.getLogger(__name__)


class _ResolvedAttachment(BaseModel):
    """The fetchable DIAL ``url`` plus display ``mime``/``title`` for one attachment."""

    model_config = ConfigDict(frozen=True)

    url: str
    mime: str
    title: str


@inject
class _GetContentTool(StagedBaseTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_GetContentStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        orchestrator_capabilities: OrchestratorCapabilities,
        messages_mixin: MessagesMixin,
        deferred_stage_close_registry: DeferredStageCloseRegistry,
        materializer: _AttachmentMaterializer,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            perf_timer=perf_timer,
            tool_config=tool_config,
            stage_display_level=StageDisplayLevel.INFO,
            deferred_stage_close_registry=deferred_stage_close_registry,
            argument_transformers=argument_transformers,
            **kwargs,
        )
        self.__messages_mixin: MessagesMixin = messages_mixin
        self.__orchestrator_capabilities: OrchestratorCapabilities = orchestrator_capabilities
        self.__stage_close_registry: DeferredStageCloseRegistry = deferred_stage_close_registry
        self.__materializer: _AttachmentMaterializer = materializer

    def _error_result(self, message: str) -> ToolCallResult:
        response = fail_response(
            message=message,
            accepted_types=list(self.__orchestrator_capabilities.input_attachment_types or []),
        )
        content, state = build_tool_result_parts(response)
        return ToolCallResult(content=content, content_type="text/plain", state=state)

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        tool_call_id: str | None = None,
        attachment_url: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        if attachment_url is None or not str(attachment_url).strip():
            logger.info("get_content tool rejected: empty attachment_url")
            return self._error_result("Missing or empty attachment_url.")

        normalized_url = normalize_attachment_url_argument(str(attachment_url))
        scheme = self.__materializer.classify(normalized_url)
        if scheme == UrlScheme.EXTERNAL:
            # Promote to a durable DIAL file the deployment can fetch; the promoted url
            # rides only on the attachment, while the payload echoes the original url.
            try:
                resolved = await self._resolve_external(normalized_url)
            except InvalidToolCallParameterException as exc:
                logger.info("get_content tool rejected: external promotion failed (%s)", exc)
                return self._error_result(str(exc))
        elif scheme == UrlScheme.DIAL:
            if not normalized_url.startswith("files/"):
                logger.info("get_content tool rejected: URL does not start with files/")
                return self._error_result("Invalid storage path for attachment file.")
            resolved = self._resolve_dial(normalized_url)
        else:
            logger.info("get_content tool rejected: unsupported url scheme")
            return self._error_result("Invalid storage path for attachment file.")

        if not self.__orchestrator_capabilities.orchestrator_accepts_mime_type(resolved.mime):
            logger.info(
                "get_content tool rejected: orchestrator does not accept MIME %s for deployment id=%s",
                resolved.mime,
                self.__orchestrator_capabilities.deployment_id,
            )
            return self._error_result("Orchestrator deployment does not accept this file type.")

        return self._build_result(
            stage_wrapper,
            tool_call_id,
            payload_url=normalized_url,
            resolved=resolved,
        )

    async def _resolve_external(self, normalized_url: str) -> _ResolvedAttachment:
        """Promote an external url to a durable DIAL file and resolve its display
        metadata. Raises ``InvalidToolCallParameterException`` if promotion is blocked.
        """
        promoted = await self.__materializer.materialize_external(normalized_url)
        attachment_file_url = normalize_attachment_url_argument(str(promoted.url))
        mime = promoted.type or inferred_mime_type_for_file_context_url(attachment_file_url)
        title = str(promoted.title) if promoted.title else attachment_file_url.rsplit("/", 1)[-1]
        return _ResolvedAttachment(url=attachment_file_url, mime=mime, title=title)

    def _resolve_dial(self, normalized_url: str) -> _ResolvedAttachment:
        """Resolve display metadata for a DIAL ``files/`` url. Honors an explicit
        type/title when the url matches a user attachment; otherwise infers from the
        filename. (A matching admin context carries no explicit type/title, so it
        yields the same inference as the fallback.)
        """
        matched = next(
            (
                att
                for att in user_attachments_from_messages(self.__messages_mixin.messages)
                if att.url and normalize_attachment_url_argument(str(att.url)) == normalized_url
            ),
            None,
        )
        if matched is not None:
            mime = attachment_mime_type(matched)
            title = str(matched.title) if matched.title else normalized_url.rsplit("/", 1)[-1]
        else:
            mime = inferred_mime_type_for_file_context_url(normalized_url)
            title = normalized_url.rsplit("/", 1)[-1]
        return _ResolvedAttachment(url=normalized_url, mime=mime, title=title)

    def _build_result(
        self,
        stage_wrapper: BaseStageWrapper | None,
        tool_call_id: str | None,
        *,
        payload_url: str,
        resolved: _ResolvedAttachment,
    ) -> ToolCallResult:
        attachment = Attachment(
            title=resolved.title,
            type=resolved.mime or "application/octet-stream",
            url=resolved.url,
        )
        response = success_response(
            display_url=payload_url,
            title=resolved.title,
            mime_type=str(attachment.type or ""),
        )
        content, state = build_tool_result_parts(response)
        result = ToolCallResult(
            content=content,
            content_type="text/plain",
            attachments=[attachment],
            state=state,
        )
        logger.debug(
            "get_content tool allowed: deployment_id=%s url_basename=%s type=%s",
            self.__orchestrator_capabilities.deployment_id,
            resolved.title,
            attachment.type,
        )
        if stage_wrapper:
            self._apply_to_stage(result, stage_wrapper, tool_call_id)
        return result

    def _apply_to_stage(
        self,
        result: ToolCallResult,
        stage_wrapper: BaseStageWrapper,
        tool_call_id: str | None,
    ) -> None:
        display = self._tool_config.display
        defer_close = bool(display and display.stage and display.stage.defer_close)
        if not defer_close:
            stage_wrapper.add_result(result)
            return

        def apply_success_to_stage() -> None:
            stage_wrapper.add_result(result)

        self.__stage_close_registry.register_stage_ui_before_close(
            stage_wrapper,
            apply_success_to_stage,
            tool_call_id=tool_call_id,
        )
