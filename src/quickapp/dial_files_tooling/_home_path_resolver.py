from injector import inject

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.config.dial_files import DialFilesConfig
from quickapp.dial_core_services.dial_file_service import DialFileService


@inject
class _HomePathResolver:
    """Resolves agent-home-relative paths to absolute DIAL file URLs and back.

    The agent home prefix (``files/{appdata}/{agent_home_dir}``) is resolved once
    per request (it may require a ``my_appdata_home()`` API call) and cached. Shared
    by the file tools and the path-argument transformer so the home is resolved a
    single time per request.
    """

    def __init__(
        self,
        dial_file_service: DialFileService,
        dial_files_config: DialFilesConfig,
    ) -> None:
        self._dial_file_service = dial_file_service
        self._dial_files_config = dial_files_config
        self._resolved_home: str | None = None

    async def resolve_appdata_url(self, path: str) -> str:
        if not isinstance(path, str) or path == "":
            raise InvalidToolCallParameterException("path", "path must be a non-empty string")
        if "\n" in path or "\r" in path:
            raise InvalidToolCallParameterException(
                "path", "path must not contain newline characters"
            )
        if path.startswith("files/"):
            return path
        self.validate_relative_path(path)
        home = await self.resolve_home_dir()
        return f"{home}{path}"

    async def resolve_home_dir(self) -> str:
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

    async def to_display_path(self, url: str) -> str:
        """Inverse of resolve_appdata_url.

        Async because home-dir resolution may require ``my_appdata_home()`` on first
        call; subsequent calls return from cache.
        """
        try:
            home = await self.resolve_home_dir()
        except InvalidToolCallParameterException:
            return url
        if url.startswith(home):
            return url[len(home) :]
        return url

    @staticmethod
    def validate_relative_path(path: str) -> None:
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
    def reject_absolute_path(parameter_name: str, tool_name: str, value: str) -> None:
        if value.startswith("files/"):
            raise InvalidToolCallParameterException(
                parameter_name,
                f"{tool_name} requires a relative path under agent_home_dir; "
                "do not pass an absolute files/... URL",
            )
