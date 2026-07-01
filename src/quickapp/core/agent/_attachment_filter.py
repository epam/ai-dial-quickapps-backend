import copy
import logging

from aidial_sdk.chat_completion import Attachment, Message, Role
from injector import inject

from quickapp.common.abstract.base_transformer import PreInvocationTransformer
from quickapp.common.abstract.tool_attachment_keep_policy import AttachmentKeepPolicy
from quickapp.common.attachment_processing_utils import build_attachment_xml_metadata

logger = logging.getLogger(__name__)


@inject
class _AttachmentFilter(PreInvocationTransformer):
    def __init__(
        self,
        tool_attachment_keep_policies: list[AttachmentKeepPolicy],
    ) -> None:
        self.__tool_attachment_keep_policies: list[AttachmentKeepPolicy] = (
            tool_attachment_keep_policies
        )

    @staticmethod
    def _has_attachments(message: Message) -> bool:
        return message.custom_content is not None and bool(message.custom_content.attachments)

    def _should_keep(
        self, messages: list[Message], message_index: int, attachment: Attachment
    ) -> bool:
        return any(
            policy.should_keep(messages, message_index, attachment)
            for policy in self.__tool_attachment_keep_policies
        )

    def _filter(
        self,
        messages: list[Message],
        message_index: int,
        message: Message,
    ) -> Message:
        updated_attachments: list[Attachment] = []
        if message.content is None:
            message.content = ""
        content = message.content if isinstance(message.content, str) else str(message.content)
        all_attachments: list[Attachment] = []
        for attachment in message.custom_content.attachments:  # type: ignore[union-attr]
            if self._should_keep(messages, message_index, attachment):
                updated_attachments.append(attachment)
            all_attachments.append(attachment)
        # Surface attachment URL/title via XML — bytes are stripped by the
        # adapter and the URL would otherwise be lost. Skip ASSISTANT:
        # re-presenting the model's own prior attachments conditions it to
        # mimic the XML format in responses.
        if message.role != Role.ASSISTANT:
            content += "\n" + build_attachment_xml_metadata(all_attachments)
        message.custom_content.attachments = updated_attachments  # type: ignore[union-attr]
        message.content = content

        return message

    def transform(self, messages: list[Message]) -> list[Message]:
        for policy in self.__tool_attachment_keep_policies:
            policy.prepare(messages)
        return [
            (
                self._filter(messages, i, copy.deepcopy(item))
                if self._has_attachments(item)
                else item
            )
            for i, item in enumerate(messages)
        ]
