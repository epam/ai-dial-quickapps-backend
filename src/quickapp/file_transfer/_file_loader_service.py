import asyncio
import logging
import mimetypes

from injector import inject

from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.state_holder import StateHolder
from quickapp.common.url_classification import UrlScheme, classify_url, unsupported_scheme_error
from quickapp.dial_core_services.dial_downloader import DialDownloader
from quickapp.file_transfer.file_source import FileSource
from quickapp.shared.external_fetch.external_url_fetcher import (
    ExternalFetchDisabledError,
    ExternalFetchError,
    ExternalUrlFetcher,
)

logger = logging.getLogger(__name__)

_DEFAULT_CONTENT_TYPE = "application/octet-stream"


def _normalize_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    base = content_type.split(";", 1)[0].strip()
    return base or None


@inject
class FileLoaderService:
    """Scheme-aware bytes loader for any file URL the agent encounters.

    Dispatches on :func:`classify_url` and applies the per-request bytes cache
    via :class:`StateHolder`. The single entry point used by callers that need
    the *bytes* of a URL (today: ``FilePrefixHandlers.handle_base64``,
    ``handle_text``, and ``handle_data`` via ``_FileArgumentTransformer``).
    """

    def __init__(
        self,
        dial_downloader: DialDownloader,
        external_fetcher: ExternalUrlFetcher,
        state_holder: StateHolder,
        dial_settings: DialSettings,
        file_sources: list[FileSource],
    ) -> None:
        self.__file_sources = file_sources
        self.__dial_downloader = dial_downloader
        self.__external_fetcher = external_fetcher
        self.__state_holder = state_holder
        self.__dial_url = dial_settings.url
        self.__inflight: dict[str, asyncio.Task[bytes]] = {}

    async def load(self, url: str, parameter_name: str = "<unknown>") -> bytes:
        cached = self.__state_holder.get_file_data(url=url)
        if cached is not None:
            return cached

        inflight = self.__inflight.get(url)
        if inflight is not None:
            return await inflight

        task = asyncio.create_task(self.__do_load(url, parameter_name))
        self.__inflight[url] = task
        try:
            return await task
        finally:
            self.__inflight.pop(url, None)

    async def load_with_content_type(
        self, url: str, parameter_name: str = "<unknown>"
    ) -> tuple[bytes, str]:
        """Load file bytes and resolve a MIME type for data-URI envelopes."""
        data = await self.load(url, parameter_name=parameter_name)
        return data, self.__resolve_content_type(url)

    def __resolve_content_type(self, url: str) -> str:
        stored = _normalize_content_type(self.__state_holder.get_content_type(url))
        if stored:
            return stored

        filename = url.rsplit("/", 1)[-1]
        guessed = _normalize_content_type(mimetypes.guess_type(filename)[0])
        if guessed:
            return guessed

        return _DEFAULT_CONTENT_TYPE

    async def __do_load(self, url: str, parameter_name: str) -> bytes:
        source = next((s for s in self.__file_sources if s.handles(url)), None)
        if source is not None:
            return await self.__load_from_source(source, url, parameter_name)

        scheme = classify_url(url, self.__dial_url)
        if scheme == UrlScheme.DIAL:
            return await self.__load_dial(url)
        if scheme == UrlScheme.EXTERNAL:
            return await self.__load_external(url, parameter_name)
        raise unsupported_scheme_error(url, parameter_name)

    async def __load_from_source(self, source: FileSource, url: str, parameter_name: str) -> bytes:
        data = await source.load(url, parameter_name)
        self.__state_holder.store_file_data(url, data, None)
        return data

    async def __load_dial(self, url: str) -> bytes:
        data, metadata = await self.__dial_downloader.fetch(url)
        # Store the metadata alongside the bytes so a later DialFileService.download_file
        # cache-hit returns a real FileMetadata (callers like _edit_file_tool need
        # metadata.etag for If-Match).
        self.__state_holder.store_file_data(url, data, metadata)
        return data

    async def __load_external(self, url: str, parameter_name: str) -> bytes:
        try:
            fetched = await self.__external_fetcher.fetch(url)
        except (ExternalFetchError, ExternalFetchDisabledError) as exc:
            raise InvalidToolCallParameterException(
                parameter_name=parameter_name, message=str(exc)
            ) from exc
        # The external Content-Type is stored separately for data: URI envelopes.
        self.__state_holder.store_file_data(
            url, fetched.data, None, content_type=fetched.content_type
        )
        return fetched.data
