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
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.dial_files_tooling._stage_wrapper import _FileStageWrapper

logger = logging.getLogger(__name__)


@inject
class _DialFileTool(StagedBaseTool, ABC):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_FileStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        dial_file_service: DialFileService,
        dial_files_config: DialFilesConfig,
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
        self._resolved_home: str | None = None

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

    async def _resolve_appdata_url(self, path: str) -> str:
        if not isinstance(path, str) or path == "":
            raise InvalidToolCallParameterException("path", "path must be a non-empty string")
        if "\n" in path or "\r" in path:
            raise InvalidToolCallParameterException(
                "path", "path must not contain newline characters"
            )
        if path.startswith("files/"):
            return path
        self._validate_relative_path(path)
        home = await self._resolve_home_dir()
        return f"{home}{path}"

    async def _resolve_home_dir(self) -> str:
        if self._resolved_home is not None:
            return self._resolved_home
        appdata = await self._dial_file_service.my_appdata_home()
        if appdata is None:
            raise InvalidToolCallParameterException(
                "path",
                "appdata namespace is not available; cannot resolve agent home directory",
            )
        subdir = self._dial_files_config.agent_home_dir
        self._resolved_home = f"files/{appdata}/{subdir}"
        return self._resolved_home

    async def _to_display_path(self, url: str) -> str:
        """Inverse of _resolve_appdata_url.

        Async because home-dir resolution may require `my_appdata_home()` on first call;
        subsequent calls return from cache.
        """
        try:
            home = await self._resolve_home_dir()
        except InvalidToolCallParameterException:
            return url
        if url.startswith(home):
            return url[len(home) :]
        return url

    @staticmethod
    def _validate_relative_path(path: str) -> None:
        if path != path.strip():
            raise InvalidToolCallParameterException(
                "path", "path must not have leading/trailing whitespace"
            )
        if path.startswith("/"):
            raise InvalidToolCallParameterException("path", "path must not start with '/'")
        segments = path.split("/")
        if ".." in segments:
            raise InvalidToolCallParameterException("path", "path must not contain '..'")
        # Trailing '' (caused by a trailing '/') is allowed to denote a folder URL.
        if "" in segments[:-1]:
            raise InvalidToolCallParameterException("path", "path must not contain empty segments")

    @staticmethod
    def _reject_absolute_path(parameter_name: str, tool_name: str, value: str) -> None:
        if value.startswith("files/"):
            raise InvalidToolCallParameterException(
                parameter_name,
                f"{tool_name} requires a relative path under agent_home_dir; "
                "do not pass an absolute files/... URL",
            )

    @staticmethod
    def _check_permission_denied(
        exc: DialException, url: str, parameter_name: str = "path"
    ) -> None:
        if exc.status_code == 403:
            raise InvalidToolCallParameterException(
                parameter_name, f"access denied: {url}"
            ) from exc
