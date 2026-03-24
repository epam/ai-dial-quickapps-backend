import logging

from aidial_client import AsyncDial
from injector import inject

from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.state_holder import StateHolder

logger = logging.getLogger(__name__)


@inject
class DialFileService:

    def __init__(
        self,
        dial_client: AsyncDial,
        state_holder: StateHolder,
        perf_timer: PerformanceTimer,
    ):
        self.__dial_client: AsyncDial = dial_client
        self.__state_holder: StateHolder = state_holder
        self.__content_size_limit = 10 * 1024 * 1024

    async def download_file(self, file_url: str) -> bytes:
        logger.debug(f"File url to download url:{file_url}")
        file_data = self.__state_holder.get_file_data(url=file_url)
        if file_data is None:
            try:
                logger.debug(f"Downloading file:{file_url}")
                metadata = await self.__dial_client.files.get_metadata(file_url)
                size = metadata.content_length or 0
                if size > self.__content_size_limit:
                    raise ValueError(
                        f"File size {size} exceeds the limit of {self.__content_size_limit} bytes."
                    )
                file_data = (await self.__dial_client.files.download(file_url)).get_content()
                self.__state_holder.store_file_data(file_url, file_data)
            except Exception as e:
                logger.error("Failed to download: %s", file_url, exc_info=True)
                raise e
        return file_data

    async def grant_permissions_to_files(
        self, files_to_share: list[str], dial_toolset_id: str
    ) -> None:
        try:
            logger.debug(f"Granting permissions to files: {files_to_share}")
            await self.__dial_client.resource_permissions.grant(
                resources=files_to_share,
                receiver=dial_toolset_id,
            )
        except Exception as e:
            logger.error(
                "Failed to grant permissions to the files %s", files_to_share, exc_info=True
            )
            raise e
