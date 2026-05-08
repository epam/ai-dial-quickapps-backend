import logging

from aidial_client import AsyncDial
from aidial_client.types.metadata import FileMetadata
from injector import inject

from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.file_reference_pattern import strip_file_prefix
from quickapp.common.url_classification import UrlScheme, classify_url, unsupported_scheme_error
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.file_transfer._external_url_fetcher import (
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
    factored helper.
    """

    def __init__(
        self,
        dial_client: AsyncDial,
        external_fetcher: ExternalUrlFetcher,
        attachment_service: AttachmentService,
        dial_settings: DialSettings,
    ) -> None:
        self.__dial_client = dial_client
        self.__external_fetcher = external_fetcher
        self.__attachment_service = attachment_service
        self.__dial_url = dial_settings.url
        self.__cache: dict[str, FileMetadata] = {}

    async def promote(self, url: str, parameter_name: str = "<unknown>") -> FileMetadata:
        cached = self.__cache.get(url)
        if cached is not None:
            return cached

        scheme = classify_url(url, self.__dial_url)
        if scheme == UrlScheme.DIAL:
            metadata = await self.__dial_client.files.get_metadata(strip_file_prefix(url))
        elif scheme == UrlScheme.EXTERNAL:
            try:
                fetched = await self.__external_fetcher.fetch(url)
            except (ExternalFetchError, ExternalFetchDisabledError) as exc:
                raise InvalidToolCallParameterException(
                    parameter_name=parameter_name, message=str(exc)
                ) from exc
            metadata = await self.__attachment_service.upload_bytes(
                data=fetched.data,
                content_type=fetched.content_type,
                filename=fetched.filename,
            )
        else:
            raise unsupported_scheme_error(url, parameter_name)

        self.__cache[url] = metadata
        return metadata
