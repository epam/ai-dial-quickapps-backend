import asyncio
import hashlib
import logging

from aidial_client import AsyncDial
from aidial_client.types.metadata import FileItem, FileMetadata
from injector import inject

from quickapp.common.data_uri import is_data_uri, parse_data_uri
from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.file_reference_pattern import strip_file_prefix
from quickapp.common.url_classification import UrlScheme, classify_url, unsupported_scheme_error
from quickapp.common.utils import generate_attachment_filename
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
)
from quickapp.shared.external_fetch.external_url_fetcher import (
    ExternalFetchDisabledError,
    ExternalFetchError,
    ExternalUrlFetcher,
)

logger = logging.getLogger(__name__)


@inject
class DialFilePromoter:
    """Materialise any URL as a durable DIAL file and return its metadata.

    Single API for the deployment-attachment fallback (when the deployment
    does not support ``url_attachments``) and the Python interpreter staging
    of external files. DIAL paths pass through; external URLs are fetched via
    :class:`ExternalUrlFetcher` and uploaded via the :class:`AttachmentService`
    factored helper; a ``data:`` URI is decoded once and uploaded through that
    same helper, so a target that needs a fetchable URL gets one.
    """

    def __init__(
        self,
        dial_client: AsyncDial,
        external_fetcher: ExternalUrlFetcher,
        attachment_service: AttachmentService,
        dial_settings: DialSettings,
        size_limit: FileLoadingSizeLimitResolver,
    ) -> None:
        self.__dial_client = dial_client
        self.__external_fetcher = external_fetcher
        self.__attachment_service = attachment_service
        self.__dial_url = dial_settings.url
        self.__size_limit = size_limit
        self.__cache: dict[str, asyncio.Task[FileMetadata | FileItem]] = {}

    async def promote(self, url: str, parameter_name: str = "<unknown>") -> FileMetadata | FileItem:
        key = self.__cache_key(url)
        task = self.__cache.get(key)
        if task is not None:
            return await task

        task = asyncio.create_task(self.__do_promote(url, parameter_name))
        self.__cache[key] = task
        try:
            return await task
        except BaseException:
            self.__cache.pop(key, None)
            raise

    @staticmethod
    def __cache_key(url: str) -> str:
        """Digest ``data:`` URIs so a multi-MB payload is never a dict key (hashing it on
        every lookup would be wasted work); other URLs are short and key themselves."""
        if is_data_uri(url):
            return f"data:{hashlib.sha256(url.encode()).hexdigest()}"
        return url

    async def __do_promote(self, url: str, parameter_name: str) -> FileMetadata | FileItem:
        if is_data_uri(url):
            return await self.__promote_data_uri(url, parameter_name)

        scheme = classify_url(url, self.__dial_url)
        if scheme == UrlScheme.DIAL:
            return await self.__dial_client.files.get_metadata(strip_file_prefix(url))
        if scheme == UrlScheme.EXTERNAL:
            try:
                fetched = await self.__external_fetcher.fetch(url)
            except (ExternalFetchError, ExternalFetchDisabledError) as exc:
                raise InvalidToolCallParameterException(
                    parameter_name=parameter_name, message=str(exc)
                ) from exc
            return await self.__attachment_service.upload_bytes(
                data=fetched.data,
                content_type=fetched.content_type,
                filename=fetched.filename,
            )
        raise unsupported_scheme_error(url, parameter_name)

    async def __promote_data_uri(self, url: str, parameter_name: str) -> FileItem:
        """Decode inline content once and upload it as a durable DIAL file.

        Error messages here must stay payload-free: they are handed back to the model as a
        retry instruction, and a multi-MB base64 blob in one would blow the context window.
        """
        try:
            parsed = parse_data_uri(url)
        except ValueError as exc:
            logger.warning("Rejected a malformed data: URI for parameter %s", parameter_name)
            raise InvalidToolCallParameterException(
                parameter_name=parameter_name,
                message=(
                    f"Parameter `{parameter_name}` carries a malformed data: URI. "
                    "Pass a DIAL file path (e.g. files/bucket/foo.pdf) instead."
                ),
            ) from exc

        limit = self.__size_limit.resolve()
        if len(parsed.data) > limit:
            raise InvalidToolCallParameterException(
                parameter_name=parameter_name,
                message=(
                    f"Inline data: content for parameter `{parameter_name}` is "
                    f"{len(parsed.data)} bytes, over the {limit}-byte file size limit. "
                    "Upload the file to DIAL and pass `files/...` instead."
                ),
            )

        filename = generate_attachment_filename(parsed.media_type)
        logger.debug(
            "Promoting inline data: content for parameter %s (type=%s, bytes=%d) to %s",
            parameter_name,
            parsed.media_type,
            len(parsed.data),
            filename,
        )
        return await self.__attachment_service.upload_bytes(
            data=parsed.data,
            content_type=parsed.media_type,
            filename=filename,
        )
