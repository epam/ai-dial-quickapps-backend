from typing import Any

from aidial_sdk.chat_completion import Attachment
from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.utils import filename_from_url_path
from quickapp.representation_tooling._attachment_resolution import build_attachment


@inject
class _AddAttachmentStageWrapper(TimedStageWrapper):

    def _get_stage_title_from_params(self, parameters: dict[str, Any]) -> str:
        url = parameters.get("url") or ""
        title = parameters.get("title")
        try:
            name = build_attachment(url, title, parameters.get("type")).title
        except InvalidToolCallParameterException:
            # The call fails on the same check; still name the file the model asked for.
            name = title or filename_from_url_path(url)
        name = name or url
        return f" `{name}`" if name else ""

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        # The resolved attachment is rendered from the result: the raw arguments may lack
        # the inferred title extension and type.
        return ""

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"### Exception:\n\r{exception}\n\r"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return "".join(self.__format_attachment(a) for a in result.propagate_to_choice)

    @staticmethod
    def __format_attachment(attachment: Attachment) -> str:
        return (
            f"- **URL:** `{attachment.url}`\n"
            f"- **Title:** `{attachment.title}`\n"
            f"- **Type:** `{attachment.type}`\n"
        )
