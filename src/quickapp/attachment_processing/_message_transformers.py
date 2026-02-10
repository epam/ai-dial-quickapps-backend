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

class _RemoveStateTransformer(MessagesTransformer):
    def transform(self, messages: list[Message]) -> list[Message]:
        # Validate input is List[Message]
        if not isinstance(messages, list):
            raise TypeError("Data must be a list of Message objects")
        for item in messages:
            if not isinstance(item, Message):
                raise TypeError("All items must be Message instances")
            if item.custom_content:
                item.custom_content.state = None  # Remove all state temp data
        return messages

class _ReduceAttachmentTransformer(MessagesTransformer):
    SUPPORTED_ATTACHMENTS = ["image/*"]

    def transform(self, messages: list[Message]) -> list[Message]:
        # Validate input is List[Message]
        if not isinstance(messages, list):
            raise TypeError("Data must be a list of Message objects")
        for item in messages:
            if not isinstance(item, Message):
                raise TypeError("All items must be Message instances")
            self._transform_item(item)
        return messages

    def _transform_item(self, message: Message):
        updated_attachments = []
        if message.content is None:
            message.content = StrictStr("")
        if message.custom_content is not None and message.custom_content.attachments:
            for attachment in message.custom_content.attachments:
                if message.role == Role.USER and matches_type(
                    attachment.type, self.SUPPORTED_ATTACHMENTS
                ):
                    updated_attachments.append(attachment)
                # Inform agent that message had contained some attachment.
                # As adapter would resolve the actual bytes and URL would be lost.
                message.content += (
                    f"\n\rAttachment {attachment.title}, of type {attachment.type}, "
                    f"url {attachment.url}, reference_url {attachment.reference_url}\n\r"
                )
            message.custom_content.attachments = updated_attachments

        return message

class _AddContextAttachmentTransformer(MessagesTransformer):
    @inject
    def __init__(self, config_provider: ProviderOf[ApplicationConfig]):
        self.__config_provider = config_provider

    def transform(self, messages: list[Message]) -> list[Message]:
        if messages and messages[-1].role == Role.USER:
            self.__append_context_files_to_last_message(messages[-1])
        return messages

    def __append_context_files_to_last_message(self, last_msg: Message):
        contexts = list(self.__config_provider.get().contexts)
        if not contexts:
            return
        for ctx in contexts:
            if isinstance(ctx, FileContextConfig):
                title = ctx.url.rsplit('/', 1)[-1]
                if not last_msg.custom_content:
                    last_msg.custom_content = CustomContent(attachments=[])
                mime_type = mimetypes.guess_type(title)[0]  # ToDo: fetch from DIAL Files API
                if matches_type(mime_type, _ReduceAttachmentTransformer.SUPPORTED_ATTACHMENTS):
                    last_msg.custom_content.attachments.append(
                        Attachment(type=mime_type, url=ctx.url, title=title)
                    )
                    logger.debug(f"File {ctx.url} added to the message.")
                else:
                    logger.debug(f"File {ctx.url} skipped, unsupported mime type: {mime_type}")