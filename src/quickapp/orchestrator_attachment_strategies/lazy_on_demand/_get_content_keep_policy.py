from aidial_sdk.chat_completion import Attachment, Message, Role
from injector import inject

from quickapp.attachment_processing._expanded_context_file_urls import ExpandedContextFileUrls
from quickapp.common.abstract.tool_attachment_keep_policy import AttachmentKeepPolicy
from quickapp.common.attachment_processing_utils import (
    attachment_mime_type,
    collect_get_content_allowed_urls,
    normalize_attachment_url_argument,
)
from quickapp.common.tool_message_utils import tool_function_name_for_tool_message
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.config.application import ApplicationConfig
from quickapp.core.agent import OrchestratorCapabilities


@inject
class _GetContentKeepPolicy(AttachmentKeepPolicy):
    """Keep an attachment when it belongs to an ``internal_attachments_get_content``
    TOOL message and its URL/MIME pass the request-allowed admin/user gate."""

    def __init__(
        self,
        app_config: ApplicationConfig,
        orchestrator_capabilities: OrchestratorCapabilities,
        expanded_file_urls: ExpandedContextFileUrls,
    ) -> None:
        self.__app_config: ApplicationConfig = app_config
        self.__orchestrator_capabilities: OrchestratorCapabilities = orchestrator_capabilities
        self.__expanded_file_urls: ExpandedContextFileUrls = expanded_file_urls
        self.__allowed_urls: set[str] = set()
        self.__get_content_tool_indices: set[int] = set()

    def prepare(self, messages: list[Message]) -> None:
        self.__get_content_tool_indices = {
            i
            for i, msg in enumerate(messages)
            if msg.role == Role.TOOL
            and tool_function_name_for_tool_message(messages, i)
            == INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
        }
        if self.__get_content_tool_indices:
            self.__allowed_urls = collect_get_content_allowed_urls(
                contexts=self.__app_config.contexts,
                messages=messages,
                input_attachment_types=self.__orchestrator_capabilities.input_attachment_types,
                expanded_folder_file_urls=self.__expanded_file_urls.urls,
            )
        else:
            self.__allowed_urls = set()

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
        if normalized not in self.__allowed_urls:
            return False
        # Use ``attachment_mime_type`` (with URL filename fallback) for symmetry
        # with the synthetic injector's gate and with ``_GetContentTool``'s own
        # check — otherwise an attachment whose ``type`` is empty but whose URL
        # implies an accepted MIME would be injected and then stripped here.
        if not self.__orchestrator_capabilities.orchestrator_accepts_mime_type(
            attachment_mime_type(attachment)
        ):
            return False
        return True
