from injector import inject

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.project_context import PROJECT_CONTEXT, has_unsafe_segments
from quickapp.common.utils import canonical_url
from quickapp.config.dial_files import DialFilesConfig
from quickapp.dial_core_services.dial_file_service import DialFileService


def _validate_relative_path(path: str) -> None:
    """Reject relative paths that are unsafe or malformed (leading '/', '..', etc.).

    Deliberately laxer than ``is_appdir_relative`` in ``common.url_classification``:
    this guards ``path`` parameters already known to be home-relative (file tools
    pass dirs without a trailing slash, arbitrary names, etc.), while the predicate
    detects the convention in arbitrary strings.
    """
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


@inject
class HomePathResolver:
    """Resolves agent-home-relative paths to absolute DIAL file URLs and back.

    The agent home is the project's ``artifacts/`` folder in a project chat (shared by every
    chat and app of the project; ``agent_home_dir`` is ignored there), and
    ``files/{appdata}/{agent_home_dir}`` otherwise. It is resolved once per request (outside
    a project it may require a ``my_appdata_home()`` API call) and cached. Shared by the file
    tools, the path-argument transformer, and any other agent-home consumer so the home is
    resolved a single time per request.

    Absolute URLs are ``files/...`` and, in a project, URLs of that project; any other
    ``projects/...`` string is an ordinary home-relative path.
    """

    def __init__(
        self,
        dial_file_service: DialFileService,
        dial_files_config: DialFilesConfig,
        project: PROJECT_CONTEXT,
    ) -> None:
        self._dial_file_service = dial_file_service
        self._dial_files_config = dial_files_config
        self._project = project
        self._resolved_home: str | None = None

    @property
    def project(self) -> PROJECT_CONTEXT:
        """The request's project, or ``None`` outside a project."""
        return self._project

    def is_absolute(self, path: str) -> bool:
        """Whether ``path`` is an absolute URL: ``files/...`` or a file of the request's project."""
        return path.startswith("files/") or (
            self._project is not None and self._project.contains(path)
        )

    async def resolve_appdata_url(self, path: str) -> str:
        if not isinstance(path, str) or path == "":
            raise InvalidToolCallParameterException("path", "path must be a non-empty string")
        if "\n" in path or "\r" in path:
            raise InvalidToolCallParameterException(
                "path", "path must not contain newline characters"
            )
        if path.startswith("files/"):
            return path
        if self._project is not None:
            if self._project.contains(path):
                return canonical_url(path)
            _validate_relative_path(path)
            # Canonicalizing decodes each segment, so check the decoded form first:
            # `%2e%2e` or an encoded `/` would otherwise turn into a real `..` or `/`.
            if has_unsafe_segments(path):
                raise InvalidToolCallParameterException(
                    "path",
                    "path must not contain '.', '..' or empty segments, or an encoded '/'",
                )
            # Canonical, like the URLs Core lists, so prefix math against listings works.
            return canonical_url(f"{await self.resolve_home_dir()}{path}")
        _validate_relative_path(path)
        home = await self.resolve_home_dir()
        return f"{home}{path}"

    async def resolve_home_dir(self) -> str:
        if self._resolved_home is not None:
            return self._resolved_home
        if self._project is not None:
            self._resolved_home = self._project.artifacts_root
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
        if self._project is not None and self._project.contains(url):
            # The model may spell a project URL decoded (``My Project``); compare canonically.
            canonical = canonical_url(url)
            return canonical[len(home) :] if canonical.startswith(home) else url
        if url.startswith(home):
            return url[len(home) :]
        return url
