from aidial_sdk.chat_completion import Attachment, Message, Role
from injector import inject

from quickapp.common.abstract.tool_attachment_keep_policy import AttachmentKeepPolicy
from quickapp.common.attachment_processing_utils import (
    attachment_mime_type,
    normalize_attachment_url_argument,
)
from quickapp.common.tool_message_utils import tool_function_name_for_tool_message
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.core.agent import OrchestratorCapabilities


@inject
class _GetContentKeepPolicy(AttachmentKeepPolicy):
    """Keep an attachment when it belongs to an ``internal_attachments_get_content``
    TOOL message, points at a DIAL ``files/`` path, and its MIME is accepted by the
    orchestrator.

    Authorization of the underlying fetch is enforced upstream — DIAL Core gates
    ``files/`` access by the caller's permissions and the external-fetch policy gates
    promoted ``http(s)`` urls — so no in-app url allow-set is consulted here.
    """

    def __init__(
        self,
        orchestrator_capabilities: OrchestratorCapabilities,
    ) -> None:
        self.__orchestrator_capabilities: OrchestratorCapabilities = orchestrator_capabilities
        self.__get_content_tool_indices: set[int] = set()

    def prepare(self, messages: list[Message]) -> None:
        self.__get_content_tool_indices = {
            i
            for i, msg in enumerate(messages)
            if msg.role == Role.TOOL
            and tool_function_name_for_tool_message(messages, i)
            == INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
        }

    def should_keep(
        self,
        messages: list[Message],
        message_index: int,
        attachment: Attachment,
    ) -> bool:
        if message_index not in self.__get_content_tool_indices:
            return False
        if not attachment.url:
            return False
        normalized = normalize_attachment_url_argument(str(attachment.url))
        if not normalized.startswith("files/"):
            return False
        # Match the synthetic injector's MIME gate (with URL-filename fallback) so an
        # attachment with an empty ``type`` but an accepted URL isn't injected upstream
        # and then stripped here.
        if not self.__orchestrator_capabilities.orchestrator_accepts_mime_type(
            attachment_mime_type(attachment)
        ):
            return False
        return True
