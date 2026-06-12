from pathlib import PurePosixPath
from unittest.mock import AsyncMock, MagicMock

from quickapp.config.dial_files import DialFilesConfig
from quickapp.dial_core_services.dial_file_service import DialFileService


def make_dial_client(appdata: str | None = "appbucket") -> MagicMock:
    client = MagicMock()
    client.my_appdata_home = AsyncMock(return_value=PurePosixPath(appdata) if appdata else None)
    client.files = MagicMock()
    client.files.delete = AsyncMock(return_value=None)
    client.files.get_metadata = AsyncMock()
    return client


def make_service(appdata: str | None = "appbucket") -> MagicMock:
    service = MagicMock(spec=DialFileService)
    service.my_appdata_home = AsyncMock(return_value=PurePosixPath(appdata) if appdata else None)
    service.write_file = AsyncMock()
    service.delete = AsyncMock()
    service.download_file = AsyncMock()
    service.invalidate_cache = MagicMock()
    service.list_folder = AsyncMock()
    service.copy = AsyncMock()
    service.move = AsyncMock()
    return service


def make_config(agent_home_dir: str = "", max_files_scanned: int = 200) -> DialFilesConfig:
    return DialFilesConfig(agent_home_dir=agent_home_dir, max_files_scanned=max_files_scanned)
