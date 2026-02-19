import logging

from injector import inject

from quickapp.common import DIAL_API_KEY
from quickapp.common.dial_core_client import DialCoreClient
from quickapp.common.dial_settings import DialSettings
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.state_holder import StateHolder

logger = logging.getLogger(__name__)


@inject
class DialFileService:

    def __init__(
        self,
        dial_settings: DialSettings,
        dial_api_key: DIAL_API_KEY,
        state_holder: StateHolder,
        perf_timer: PerformanceTimer,
    ):

        self.__dial_settings: DialSettings = dial_settings
        self.__dial_api_key: DIAL_API_KEY = dial_api_key
        self.__state_holder: StateHolder = state_holder
        self.__content_size_limit = 10 * 1024 * 1024

    async def download_file(self, file_url: str) -> bytes:
        # Check state holder for the file content:
        logger.debug(f"File url to download url:{file_url}")
        file_data = self.__state_holder.get_file_data(url=file_url)
        if file_data is None:
            try:
                logger.debug(f"Downloading file:{file_url}")
                async with DialCoreClient(
                    api_key=self.__dial_api_key, base_url=self.__dial_settings.url
                ) as dial_core:
                    metadata = await dial_core.get_metadata(file_url)
                    size = metadata.get("contentLength") or 0
                    if size > self.__content_size_limit:
                        raise ValueError(
                            f"File size {size} exceeds the limit of {self.__content_size_limit} bytes."
                        )

                    file_data = await dial_core.get_file(file_url)
                    self.__state_holder.store_file_data(file_url, file_data)
            except Exception as e:
                logger.error("Failed to download: %s", file_url, exc_info=True)
                raise e
        return file_data


    async def grant_permissions_to_files(
        self, files_to_share: list[str], dial_toolset_id: str
    ) -> None:
        async with DialCoreClient(
            api_key=self.__dial_api_key, base_url=self.__dial_settings.url
        ) as dial_core:
            try:
                logger.debug(f"Granting permissions to files: {files_to_share}")
                await dial_core.grant_permissions(files_to_share, dial_toolset_id)
            except Exception as e:
                logger.error(e)
                raise e
