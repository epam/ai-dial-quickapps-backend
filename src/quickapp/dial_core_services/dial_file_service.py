import logging

from aidial_client import AsyncDial
from injector import inject

logger = logging.getLogger(__name__)


@inject
class DialFileService:

    def __init__(self, dial_client: AsyncDial):
        self.__dial_client: AsyncDial = dial_client

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
