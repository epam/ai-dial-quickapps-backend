import logging

from aidial_sdk.chat_completion import Message, Role

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
        return [self._filter(item) if self._has_attachments(item) else item for item in messages]

    def _filter(self, message: Message) -> Message:
        updated_attachments = []
        if message.content is None:
            message.content = ""
        content = message.content if isinstance(message.content, str) else str(message.content)
        if self._has_attachments(message):
            for attachment in message.custom_content.attachments:  # type: ignore[union-attr]
                if message.role == Role.USER and matches_type(
                    attachment.type, self.SUPPORTED_ATTACHMENTS
                ):
                    updated_attachments.append(attachment)
                content += (
                    f"\r\nAttachment {attachment.title}, of type {attachment.type}, "
                    f"url {attachment.url}, reference_url {attachment.reference_url}\r\n"
                )
            message.custom_content.attachments = updated_attachments  # type: ignore[union-attr]
        message.content = content

        return message
