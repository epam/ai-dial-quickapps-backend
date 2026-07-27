import logging
from abc import ABC
from typing import Any

from aidial_client._exception import DialException, ResourceNotFoundError
from aidial_client.types.metadata import FileMetadata
from injector import AssistedBuilder, inject

from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.config.application import StageDisplayLevel
from quickapp.config.dial_files import DialFilesConfig
from quickapp.config.tools.internal import InternalTool
from quickapp.dial_core_services.dial_file_service import DialFileService, FolderEntry
from quickapp.dial_files_tooling._stage_wrapper import _FileStageWrapper
from quickapp.dial_files_tooling._utils import is_root_reference
from quickapp.shared.home_path.home_path_resolver import HomePathResolver

logger = logging.getLogger(__name__)

# Ceiling of the LLM-facing `max_depth` parameter, and the single source for the
# "Range: [1, N]" bound interpolated into the tool schema descriptions (see _tool_configs.py).
# Not configurable: a per-app value would drift from the advertised schema.
_MAX_DEPTH = 10


@inject
class _DialFileTool(StagedBaseTool, ABC):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_FileStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        dial_file_service: DialFileService,
        dial_files_config: DialFilesConfig,
        home_resolver: HomePathResolver,
        stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            stage_display_level=stage_display_level,
            argument_transformers=argument_transformers,
            **kwargs,
        )
        self._dial_file_service = dial_file_service
        self._dial_files_config = dial_files_config
        self._home_resolver = home_resolver

    async def _download_text(
        self, file_url: str, display_path: str
    ) -> tuple[str, FileMetadata | None]:
        try:
            data, metadata = await self._dial_file_service.download_file(file_url)
        except ResourceNotFoundError as e:
            raise InvalidToolCallParameterException(
                "path", f"file not found: {display_path}"
            ) from e
        except DialException as e:
            self._check_permission_denied(e, display_path)
            raise InvalidToolCallParameterException("path", f"File download failed: {e}") from e
        except Exception as e:
            raise InvalidToolCallParameterException("path", f"File download failed: {e}") from e
        return data.decode("utf-8"), metadata

    async def _read_text_for_scan(self, file_url: str) -> str | None:
        """Download and UTF-8-decode a file for folder-scan content search.

        Returns ``None`` to skip the file when it cannot be used for substring search
        anyway: a non-UTF-8/binary file (``UnicodeDecodeError``) or one exceeding the
        per-file size limit (``download_file`` raises ``ValueError``). Genuine errors
        (not-found, access-denied) propagate. This deliberately bypasses
        ``_download_text`` -- whose single-file contract wraps those same failures into
        ``InvalidToolCallParameterException`` -- so folder mode can skip cleanly instead
        of aborting the whole search.
        """
        try:
            data, _ = await self._dial_file_service.download_file(file_url)
            return data.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

    async def _resolve_folder_url(self, path: str) -> str:
        """Resolve a folder path to a 'files/...' URL ending in '/'.

        Root-of-home references resolve to the home directory directly, bypassing
        _resolve_appdata_url, whose validation rejects a leading '/' and would mangle
        './' into 'files/.../.'.
        """
        if is_root_reference(path):
            return await self._home_resolver.resolve_home_dir()
        if not path.endswith("/"):
            path = path + "/"
        return await self._home_resolver.resolve_appdata_url(path)

    async def _list_folder_entries(
        self, path: str, max_depth: int
    ) -> tuple[str, list[FolderEntry]]:
        """Resolve `path` to a folder and list it under the shared not-found policy.

        Returns the resolved `(folder_url, entries)` so callers that also need the search
        root (e.g. `find`/folder-mode `search` for relative-path glob matching) avoid
        re-resolving it.

        A missing **root** reference (nothing written yet) yields an empty list; a missing
        **non-root** folder raises "folder not found"; a non-folder target raises "not a
        folder"; permission errors surface as "access denied". Shared by `list`, `find`,
        and folder-mode `search` so all three behave identically.
        """
        folder_url = await self._resolve_folder_url(path)
        try:
            entries = await self._dial_file_service.list_folder(folder_url, max_depth=max_depth)
            return folder_url, entries
        except ResourceNotFoundError as e:
            if is_root_reference(path):
                return folder_url, []
            display = await self._home_resolver.to_display_path(folder_url)
            raise InvalidToolCallParameterException("path", f"folder not found: {display}") from e
        except ValueError as e:
            display = await self._home_resolver.to_display_path(folder_url)
            raise InvalidToolCallParameterException("path", f"not a folder: {display}") from e
        except DialException as e:
            self._check_permission_denied(e, path)
            raise

    @staticmethod
    def _resolve_max_depth(value: Any, default: int) -> int:
        """Parse and range-check `max_depth`, falling back to `default` when unset."""
        max_depth = int(value) if value is not None else default
        if max_depth < 1 or max_depth > _MAX_DEPTH:
            raise InvalidToolCallParameterException("max_depth", f"must be in [1, {_MAX_DEPTH}]")
        return max_depth

    @staticmethod
    def _check_permission_denied(
        exc: DialException, url: str, parameter_name: str = "path"
    ) -> None:
        if exc.status_code == 403:
            raise InvalidToolCallParameterException(
                parameter_name, f"access denied: {url}"
            ) from exc
