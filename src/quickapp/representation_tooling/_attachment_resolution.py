import mimetypes

from aidial_sdk.chat_completion import Attachment

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.utils import filename_from_url_path, guess_attachment_extension


def _guess_mime_type(name: str | None) -> str | None:
    return mimetypes.guess_type(name)[0] if name else None


def build_attachment(url: str, title: str | None, mime_type: str | None) -> Attachment:
    """Build the attachment the tool promotes, inferring the missing title and type.

    Shared by the tool and its stage wrapper so the stage shows what is actually attached.
    """
    url_file_name = filename_from_url_path(url)
    resolved_title: str | None = title or url_file_name
    # The chat UI derives the download extension from the type, so a text/plain guess
    # would offer any file as .txt: infer it from the extension or ask the model.
    resolved_type: str | None = (
        mime_type or _guess_mime_type(url_file_name) or _guess_mime_type(resolved_title)
    )
    if resolved_type is None:
        raise InvalidToolCallParameterException(
            "type",
            "Cannot determine the file type from the url or title. "
            "Pass `type` (MIME type, e.g. text/html) or a `title` with the file extension.",
        )
    # Keep the extension on a model-chosen title such as "Sales Report"; take it from the
    # type so the file name and the type never disagree.
    if resolved_title and not _guess_mime_type(resolved_title):
        resolved_title += guess_attachment_extension(resolved_type)

    return Attachment(url=url, title=resolved_title, type=resolved_type)
