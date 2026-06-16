from pathlib import PurePosixPath
from typing import Any, TypeVar
from unittest.mock import AsyncMock, MagicMock

from quickapp.config.dial_files import DialFilesConfig
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.dial_files_tooling._home_path_resolver import _HomePathResolver

_ToolT = TypeVar("_ToolT")


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


def make_tool(
    tool_cls: type[_ToolT],
    tool_config: Any,
    *,
    service: MagicMock | None = None,
    config: DialFilesConfig | None = None,
) -> _ToolT:
    """Build a file tool with its DI dependencies (mirrors production wiring).

    The home resolver is built from the same service/config the tool gets, so the
    tool and its resolver agree on the appdata home — as they do under DI, where the
    request-scoped resolver is shared.
    """
    service = service if service is not None else make_service()
    config = config if config is not None else make_config()
    return tool_cls(
        stage_wrapper_builder=MagicMock(),
        tool_config=tool_config,
        perf_timer=MagicMock(),
        dial_file_service=service,
        dial_files_config=config,
        home_resolver=_HomePathResolver(service, config),
    )
