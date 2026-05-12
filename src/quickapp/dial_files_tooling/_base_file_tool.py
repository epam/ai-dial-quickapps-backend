import logging
from abc import ABC
from typing import Any

from aidial_client import AsyncDial
from aidial_client._exception import DialException
from aidial_client.types.metadata import FileMetadata
from injector import AssistedBuilder, inject

from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.config.dial_files import DialFilesConfig
from quickapp.config.tools.internal import InternalTool
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.dial_files_tooling._stage_wrapper import _FileStageWrapper

logger = logging.getLogger(__name__)

_APPDATA_PLACEHOLDER = "{appdata}"


@inject
class _DialFileTool(StagedBaseTool, ABC):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_FileStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        dial_file_service: DialFileService,
        dial_client: AsyncDial,
        dial_files_config: DialFilesConfig,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            argument_transformers=argument_transformers,
            **kwargs,
        )
        self._dial_file_service = dial_file_service
        self._dial_client = dial_client
        self._dial_files_config = dial_files_config
        self._resolved_home: str | None = None

    async def _download_text(
        self, file_url: str, display_path: str
    ) -> tuple[str, FileMetadata | None]:
        try:
            data, metadata = await self._dial_file_service.download_file(file_url)
        except DialException as e:
            self._check_permission_denied(e, display_path)
            raise InvalidToolCallParameterException("path", f"File download failed: {e}") from e
        except Exception as e:
            raise InvalidToolCallParameterException("path", f"File download failed: {e}") from e
        return data.decode("utf-8"), metadata

    async def _resolve_appdata_url(self, path: str) -> str:
        if not isinstance(path, str) or path == "":
            raise InvalidToolCallParameterException("path", "path must be a non-empty string")

        if path.startswith("files/"):
            if "\n" in path or "\r" in path:
                raise InvalidToolCallParameterException(
                    "path", "absolute URL must not contain newline characters"
                )
            return path

        self._validate_relative_path(path)
        home = await self._resolve_home_dir()
        return f"{home}{path}"

    async def _resolve_home_dir(self) -> str:
        if self._resolved_home is not None:
            return self._resolved_home
        template = self._dial_files_config.agent_home_dir
        if _APPDATA_PLACEHOLDER in template:
            appdata = await self._dial_client.my_appdata_home()
            if appdata is None:
                raise InvalidToolCallParameterException(
                    "path",
                    "appdata namespace is not available; "
                    "agent_home_dir uses {appdata} but no appdata was found",
                )
            resolved = template.replace(_APPDATA_PLACEHOLDER, str(appdata))
        else:
            resolved = template
        self._resolved_home = resolved
        return resolved

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
        if "../" in path or path.endswith("/..") or path == "..":
            raise InvalidToolCallParameterException("path", "path must not contain '..'")
        segments = path.split("/")
        # Allow a trailing '' (caused by trailing '/') to represent a folder URL.
        for i, segment in enumerate(segments):
            if segment == "..":
                raise InvalidToolCallParameterException("path", "path must not contain '..'")
            if segment == "" and i != len(segments) - 1:
                raise InvalidToolCallParameterException(
                    "path", "path must not contain empty segments"
                )

    @staticmethod
    def _reject_absolute_path(parameter_name: str, tool_name: str, value: str) -> None:
        if value.startswith("files/"):
            raise InvalidToolCallParameterException(
                parameter_name,
                f"{tool_name} requires a relative path under agent_home_dir; "
                "do not pass an absolute files/... URL",
            )

    @staticmethod
    def _check_permission_denied(exc: DialException, url: str) -> None:
        if exc.status_code == 403:
            raise InvalidToolCallParameterException("path", f"access denied: {url}") from exc
