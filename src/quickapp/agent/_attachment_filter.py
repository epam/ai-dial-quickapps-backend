import copy
import logging
from xml.sax.saxutils import escape

from aidial_sdk.chat_completion import Attachment, Message, Role
from injector import inject

from quickapp.common.abstract.base_transformer import PreInvocationTransformer
from quickapp.common.attachment_processing_utils import (
    collect_get_content_allowed_urls,
    normalize_attachment_url_argument,
)
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.common.utils import matches_type
from quickapp.config.application import ApplicationConfig
from quickapp.dial_core_services.orchestrator_deployment_capabilities import (
    OrchestratorCapabilities,
)

logger = logging.getLogger(__name__)


@inject
class _AttachmentFilter(PreInvocationTransformer):
    SUPPORTED_ATTACHMENTS = ["image/*"]

    def __init__(
        self,
        app_config: ApplicationConfig,
        orchestrator_capabilities: OrchestratorCapabilities,
    ) -> None:
        self.__orchestrator_capabilities: OrchestratorCapabilities = orchestrator_capabilities
        self.__app_config: ApplicationConfig = app_config

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

    def _keep_get_content_tool_attachment(
        self, attachment: Attachment, allowed_urls: set[str]
    ) -> bool:
        if not attachment.url or not str(attachment.url).strip().startswith("files/"):
            return False
        normalized = normalize_attachment_url_argument(str(attachment.url))
        if normalized not in allowed_urls:
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
            allowed_get_content_urls: set[str] = (
                collect_get_content_allowed_urls(
                    contexts=self.__app_config.contexts,
                    messages=messages,
                    input_attachment_types=self.__orchestrator_capabilities.input_attachment_types,
                )
                if is_get_content_tool
                else set()
            )
            for attachment in message.custom_content.attachments:  # type: ignore[union-attr]
                if message.role == Role.USER and self.__orchestrator_capabilities.orchestrator_accepts_mime_type(attachment.type):
                    updated_attachments.append(attachment)
                elif is_get_content_tool and self._keep_get_content_tool_attachment(
                    attachment, allowed_get_content_urls
                ):
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
        return [
            (
                self._filter(messages, i, copy.deepcopy(item))
                if self._has_attachments(item)
                else item
            )
            for i, item in enumerate(messages)
        ]
