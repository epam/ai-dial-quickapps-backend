from io import BytesIO

from aidial_client import AsyncDial
from aidial_sdk.chat_completion import Attachment
from injector import inject

from quickapp.common import DIAL_API_KEY
from quickapp.common.dial_settings import DialSettings
from quickapp.common.tool_timeout_utils import build_async_dial_timeout
from quickapp.common.url_classification import UrlScheme, classify_url, unsupported_scheme_error
from quickapp.common.utils import posix_path_last_segment
from quickapp.file_transfer._dial_file_promoter import DialFilePromoter
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_settings import (
    _PyInterpreterSettings,
)


@inject
class InputFileHandler:
    """Handles file operations for the PyCodeInterpreterTool"""

    def __init__(
        self,
        promoter: DialFilePromoter,
        dial_settings: DialSettings,
    ) -> None:
        self.__promoter = promoter
        self.__dial_url = dial_settings.url
        self.__request_dial: AsyncDial | None = None
        self.__dev_dial: AsyncDial | None = None

    async def get_attachment_url(
        self,
        settings: _PyInterpreterSettings,
        dial_api_key: DIAL_API_KEY,
        attachment_url: str,
        attachment: Attachment,
        timeout: float,
    ) -> str:
        """Resolve a conversation attachment URL into a URL the interpreter can fetch.

        External URLs are first promoted to a DIAL file (the interpreter only
        accepts DIAL `sourceUrl`s). When a separate dev-DIAL is configured via
        ``settings.api_key``, the (possibly promoted) DIAL URL is downloaded
        from the host DIAL and re-uploaded to the dev DIAL — preserving the
        existing local-run behaviour.
        """
        scheme = classify_url(attachment_url, self.__dial_url)
        if scheme == UrlScheme.EXTERNAL:
            metadata = await self.__promoter.promote(
                attachment_url, parameter_name="attachment_urls"
            )
            effective_url = metadata.url
        elif scheme == UrlScheme.DIAL:
            effective_url = attachment_url
        else:
            raise unsupported_scheme_error(attachment_url, parameter_name="attachment_urls")

        if not settings.api_key:
            return effective_url

        request_dial = self.__get_or_build_request_dial(dial_api_key, timeout)
        dev_dial = self.__get_or_build_dev_dial(settings, timeout)

        file_content = await (await request_dial.files.download(effective_url)).aget_content()
        bucket_resp = await dev_dial.bucket.get_raw()
        bucket = bucket_resp.appdata or bucket_resp.bucket
        filename = posix_path_last_segment(effective_url)
        metadata = await dev_dial.files.upload(
            f"files/{bucket}/{filename}",
            (filename, BytesIO(file_content), attachment.type),
        )
        return metadata.url

    def __get_or_build_request_dial(self, dial_api_key: DIAL_API_KEY, timeout: float) -> AsyncDial:
        if self.__request_dial is None:
            self.__request_dial = AsyncDial(
                api_key=dial_api_key.get_secret_value(),
                base_url=self.__dial_url,
                timeout=build_async_dial_timeout(timeout),
            )
        return self.__request_dial

    def __get_or_build_dev_dial(
        self, settings: _PyInterpreterSettings, timeout: float
    ) -> AsyncDial:
        if self.__dev_dial is None:
            assert settings.api_key is not None
            self.__dev_dial = AsyncDial(
                api_key=settings.api_key.get_secret_value(),
                base_url=settings.url,
                timeout=build_async_dial_timeout(timeout),
            )
        return self.__dev_dial
