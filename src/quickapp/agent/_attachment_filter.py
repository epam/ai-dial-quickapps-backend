import copy
import logging
from xml.sax.saxutils import escape

from aidial_sdk.chat_completion import Attachment, Message, Role

from quickapp.common.abstract.base_transformer import PreInvocationTransformer
from quickapp.common.utils import matches_type

logger = logging.getLogger(__name__)


class _AttachmentFilter(PreInvocationTransformer):
    SUPPORTED_ATTACHMENTS = ["image/*"]

    @staticmethod
    def _has_attachments(message: Message) -> bool:
        return message.custom_content is not None and bool(message.custom_content.attachments)

    def transform(self, messages: list[Message]) -> list[Message]:
        for item in messages:
            if not isinstance(item, Message):
                raise TypeError("All items must be Message instances")
        return [
            self._filter(copy.deepcopy(item)) if self._has_attachments(item) else item
            for item in messages
        ]

    @staticmethod
    def _build_attachment_xml(attachments: list[Attachment]) -> str:
        xml_parts = ["<attachments>"]
        for attachment in attachments:
            xml_parts.append("  <attachment>")
            xml_parts.append(f"    <title>{escape(str(attachment.title or ''))}</title>")
            xml_parts.append(f"    <type>{escape(str(attachment.type or ''))}</type>")
            if attachment.url is not None:
                xml_parts.append(f"    <url>{escape(str(attachment.url))}</url>")
            if attachment.data is not None:
                xml_parts.append(f"    <data>{escape(str(attachment.data))}</data>")
            xml_parts.append("  </attachment>")
        xml_parts.append("</attachments>")
        return "\n".join(xml_parts)

    def _filter(self, message: Message) -> Message:
        updated_attachments = []
        if message.content is None:
            message.content = ""
        content = message.content if isinstance(message.content, str) else str(message.content)
        if self._has_attachments(message):
            all_attachments: list[Attachment] = []
            for attachment in message.custom_content.attachments:  # type: ignore[union-attr]
                if message.role == Role.USER and matches_type(
                    attachment.type, self.SUPPORTED_ATTACHMENTS
                ):
                    updated_attachments.append(attachment)
                all_attachments.append(attachment)
            # Surface attachment metadata via XML — inline data and URLs may be
            # stripped from the adapter-facing content otherwise. Skip ASSISTANT:
            # re-presenting the model's own prior attachments conditions it to
            # mimic the XML format in responses.
            if message.role != Role.ASSISTANT:
                content += "\n" + self._build_attachment_xml(all_attachments)
            message.custom_content.attachments = updated_attachments  # type: ignore[union-attr]
        message.content = content

        return message
