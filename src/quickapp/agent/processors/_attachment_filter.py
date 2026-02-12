import logging
import mimetypes

from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role
from injector import inject, ProviderOf
from pydantic import StrictStr

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.utils import matches_type
from quickapp.config.application import ApplicationConfig
from quickapp.config.context import FileContextConfig

logger = logging.getLogger(__name__)


class _AttachmentFilter:
    SUPPORTED_ATTACHMENTS = ["image/*"]

    def filter_attachments(self, messages: list[Message]) -> list[Message]:
        # Validate input is List[Message]
        if not isinstance(messages, list):
            raise TypeError("Data must be a list of Message objects")
        for item in messages:
            if not isinstance(item, Message):
                raise TypeError("All items must be Message instances")
            self._filter(item)
        return messages

    def _filter(self, message: Message):
        updated_attachments = []
        if message.content is None:
            message.content = StrictStr("")
        if message.custom_content is not None and message.custom_content.attachments:
            for attachment in message.custom_content.attachments:
                if message.role == Role.USER and matches_type(
                        attachment.type, self.SUPPORTED_ATTACHMENTS
                ):
                    updated_attachments.append(attachment)
                else:
                    # Inform agent that message had contained some attachment.
                    # As adapter would resolve the actual bytes and URL would be lost.
                    message.content += (
                        f"\n\rAttachment {attachment.title}, of type {attachment.type}, "
                        f"url {attachment.url}, reference_url {attachment.reference_url}\n\r"
                    )
            message.custom_content.attachments = updated_attachments

        return message
