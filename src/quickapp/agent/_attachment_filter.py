import copy
import logging

from aidial_sdk.chat_completion import Message, Role
from pydantic import StrictStr

from quickapp.common.utils import matches_type

logger = logging.getLogger(__name__)


class _AttachmentFilter:
    SUPPORTED_ATTACHMENTS = ["image/*"]

    @staticmethod
    def _has_attachments(message: Message) -> bool:
        return message.custom_content is not None and bool(message.custom_content.attachments)

    def filter_attachments(self, messages: list[Message]) -> list[Message]:
        for item in messages:
            if not isinstance(item, Message):
                raise TypeError("All items must be Message instances")
        return [
            self._filter(copy.deepcopy(item)) if self._has_attachments(item) else item
            for item in messages
        ]

    def _filter(self, message: Message):
        updated_attachments = []
        if message.content is None:
            message.content = StrictStr("")
        if self._has_attachments(message):
            for attachment in message.custom_content.attachments:
                if message.role == Role.USER and matches_type(
                    attachment.type, self.SUPPORTED_ATTACHMENTS
                ):
                    updated_attachments.append(attachment)
                # Inform agent that message had contained some attachment.
                # As adapter would resolve the actual bytes and URL would be lost.
                message.content += (
                    f"\r\nAttachment {attachment.title}, of type {attachment.type}, "
                    f"url {attachment.url}, reference_url {attachment.reference_url}\r\n"
                )
            message.custom_content.attachments = updated_attachments

        return message
