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
from quickapp.common.tool_message_utils import tool_function_name_for_tool_message
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.config.application import ApplicationConfig
from quickapp.dial_core_services.orchestrator_deployment_capabilities import (
    OrchestratorCapabilities,
)

logger = logging.getLogger(__name__)


@inject
class _AttachmentFilter(PreInvocationTransformer):
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

    def _is_get_content_tool_message(self, messages: list[Message], message_index: int) -> bool:
        msg = messages[message_index]
        return (
            msg.role == Role.TOOL
            and tool_function_name_for_tool_message(messages, message_index)
            == INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
        )

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

    def _filter(
        self,
        message: Message,
        is_get_content_tool: bool,
        allowed_get_content_urls: set[str],
    ) -> Message:
        updated_attachments: list[Attachment] = []
        if message.content is None:
            message.content = ""
        content = message.content if isinstance(message.content, str) else str(message.content)
        all_attachments: list[Attachment] = []
        for attachment in message.custom_content.attachments:  # type: ignore[union-attr]
            if is_get_content_tool and self._keep_get_content_tool_attachment(
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
        """
        Filters attachments in messages based on role, tool type, and capabilities.
        Pre-computes flags for efficiency and collects allowed URLs only when needed.
        """
        # Pre-fill flags for whether each message is a get_content tool message to avoid redundant checks in the attachment loop
        messages_is_get_content_tool_flag = [
            self._is_get_content_tool_message(messages, i) for i in range(len(messages))
        ]
        # Collect allowed URLs for get_content tool attachments if any get_content tool messages are present
        allowed_get_content_urls: set[str] = (
            collect_get_content_allowed_urls(
                contexts=self.__app_config.contexts,
                messages=messages,
                input_attachment_types=self.__orchestrator_capabilities.input_attachment_types,
            )
            if any(messages_is_get_content_tool_flag)
            else set()
        )
        return [
            (
                self._filter(
                    copy.deepcopy(item),
                    is_get_content_tool=messages_is_get_content_tool_flag[i],
                    allowed_get_content_urls=allowed_get_content_urls,
                )
                if self._has_attachments(item)
                else item
            )
            for i, item in enumerate(messages)
        ]
