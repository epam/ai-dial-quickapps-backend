import asyncio
import logging

from injector import inject

from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.state_holder import StateHolder
from quickapp.common.url_classification import UrlScheme, classify_url, unsupported_scheme_error
from quickapp.dial_core_services.dial_downloader import DialDownloader
from quickapp.file_transfer._external_url_fetcher import (
    ExternalFetchDisabledError,
    ExternalFetchError,
    ExternalUrlFetcher,
)

logger = logging.getLogger(__name__)


@inject
class FileLoaderService:
    """Scheme-aware bytes loader for any file URL the agent encounters.

    Dispatches on :func:`classify_url` and applies the per-request bytes cache
    via :class:`StateHolder`. The single entry point used by callers that need
    the *bytes* of a URL (today: ``FilePrefixHandlers.handle_base64`` and
    ``handle_text`` via ``_FileArgumentTransformer``).
    """

    def __init__(
        self,
        dial_downloader: DialDownloader,
        external_fetcher: ExternalUrlFetcher,
        state_holder: StateHolder,
        dial_settings: DialSettings,
    ) -> None:
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

    async def __do_load(self, url: str, parameter_name: str) -> bytes:
        scheme = classify_url(url, self.__dial_url)
        if scheme == UrlScheme.DIAL:
            data = await self.__dial_downloader.fetch(url)
        elif scheme == UrlScheme.EXTERNAL:
            try:
                fetched = await self.__external_fetcher.fetch(url)
            except (ExternalFetchError, ExternalFetchDisabledError) as exc:
                raise InvalidToolCallParameterException(
                    parameter_name=parameter_name, message=str(exc)
                ) from exc
            data = fetched.data
        else:
            raise unsupported_scheme_error(url, parameter_name)

        self.__state_holder.store_file_data(url, data)
        return data
