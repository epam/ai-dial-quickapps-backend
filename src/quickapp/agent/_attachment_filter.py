import copy
import logging
from xml.sax.saxutils import escape

from aidial_sdk.chat_completion import Attachment, Message, Role
from injector import inject

from quickapp.agent.orchestrator_deployment_capabilities import OrchestratorDeploymentCapabilities
from quickapp.attachment_processing._context_entries import normalize_context_url_argument
from quickapp.attachment_processing._tool_configs import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.common.abstract.base_transformer import PreInvocationTransformer
from quickapp.common.utils import matches_type
from quickapp.config.application import ApplicationConfig
from quickapp.config.context import FileContextConfig

logger = logging.getLogger(__name__)

@inject
class _AttachmentFilter(PreInvocationTransformer):
    SUPPORTED_ATTACHMENTS = ["image/*"]

    def __init__(
        self,
        app_config: ApplicationConfig,
        orchestrator_capabilities: OrchestratorDeploymentCapabilities,
    ) -> None:
        self.__orchestrator_capabilities: OrchestratorDeploymentCapabilities = (
            orchestrator_capabilities
        )
        self.__configured_context_urls_stripped: frozenset[str] = frozenset(
            ctx.url.strip() for ctx in app_config.contexts if isinstance(ctx, FileContextConfig)
        )

    @staticmethod
    def _has_attachments(message: Message) -> bool:
        return message.custom_content is not None and bool(message.custom_content.attachments)

    @staticmethod
    def _build_attachment_xml(attachments: list[Attachment]) -> str:
        xml_parts = ["<attachments>"]
        for attachment in attachments:
            xml_parts.append("  <attachment>")
            xml_parts.append(f"    <title>{escape(str(attachment.title or ''))}</title>")
            xml_parts.append(f"    <type>{escape(str(attachment.type or ''))}</type>")
            xml_parts.append(f"    <url>{escape(str(attachment.url or ''))}</url>")
            if attachment.reference_url is not None:
                xml_parts.append(
                    f"    <reference_url>{escape(str(attachment.reference_url))}</reference_url>"
                )
            xml_parts.append("  </attachment>")
        xml_parts.append("</attachments>")
        return "\n".join(xml_parts)

    @staticmethod
    def _tool_function_name_for_tool_message(
        messages: list[Message], message_index: int
    ) -> str | None:
        msg = messages[message_index]
        if msg.role != Role.TOOL:
            return None
        tool_call_id = msg.tool_call_id
        if not tool_call_id:
            return None
        for j in range(message_index - 1, -1, -1):
            prev = messages[j]
            if prev.role == Role.ASSISTANT and prev.tool_calls:
                for tc in prev.tool_calls:
                    if tc.id == tool_call_id and tc.function:
                        return tc.function.name
        return None

    def _keep_get_content_tool_attachment(self, attachment: Attachment) -> bool:
        if not attachment.url or not str(attachment.url).strip().startswith("files/"):
            return False
        normalized = normalize_context_url_argument(str(attachment.url))
        if normalized not in self.__configured_context_urls_stripped:
            return False
        if not self.__orchestrator_capabilities.orchestrator_accepts_mime_type(attachment.type):
            return False
        return True

    def _filter(self, messages: list[Message], message_index: int, message: Message) -> Message:
        updated_attachments: list[Attachment] = []
        if message.content is None:
            message.content = ""
        content = message.content if isinstance(message.content, str) else str(message.content)
        if self._has_attachments(message):
            all_attachments: list[Attachment] = []
            is_get_content_tool = (
                message.role == Role.TOOL
                and self._tool_function_name_for_tool_message(messages, message_index)
                == INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
            )
            for attachment in message.custom_content.attachments:  # type: ignore[union-attr]
                if message.role == Role.USER and matches_type(
                    attachment.type, self.SUPPORTED_ATTACHMENTS
                ):
                    updated_attachments.append(attachment)
                elif is_get_content_tool and self._keep_get_content_tool_attachment(attachment):
                    updated_attachments.append(attachment)
                all_attachments.append(attachment)
            # Surface attachment URL/title via XML — bytes are stripped by the
            # adapter and the URL would otherwise be lost. Skip ASSISTANT:
            # re-presenting the model's own prior attachments conditions it to
            # mimic the XML format in responses.
            if message.role != Role.ASSISTANT:
                content += "\n" + self._build_attachment_xml(all_attachments)
            message.custom_content.attachments = updated_attachments  # type: ignore[union-attr]
        message.content = content

        return message

    def transform(self, messages: list[Message]) -> list[Message]:
        for item in messages:
            if not isinstance(item, Message):
                raise TypeError("All items must be Message instances")
        return [
            (
                self._filter(messages, i, copy.deepcopy(item))
                if self._has_attachments(item)
                else item
            )
            for i, item in enumerate(messages)
        ]
