from aidial_sdk.chat_completion import Attachment, Message, Role

from quickapp.common.abstract.tool_attachment_keep_policy import ToolAttachmentKeepPolicy
from quickapp.common.utils import matches_type


class _LegacyUserImageKeepPolicy(ToolAttachmentKeepPolicy):
    """Keep ``image/*`` attachments on USER messages — the default behaviour
    inherited from `development` before policy-driven filtering replaced the
    inline `_AttachmentFilter` rule.
    """

    _SUPPORTED_USER_MIME_TYPES = ["image/*"]

    def should_keep(
        self,
        messages: list[Message],
        message_index: int,
        attachment: Attachment,
    ) -> bool:
        if messages[message_index].role != Role.USER:
            return False
        return matches_type(attachment.type, self._SUPPORTED_USER_MIME_TYPES)
