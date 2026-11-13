from injector import inject

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.project_context import PROJECT_CONTEXT, has_unsafe_segments
from quickapp.common.url_classification import is_dial_storage_path
from quickapp.common.utils import canonical_url, readable_url
from quickapp.config.dial_files import DialFilesConfig
from quickapp.dial_core_services.dial_file_service import DialFileService


def _validate_relative_path(path: str, parameter_name: str) -> None:
    """Reject relative paths that are unsafe or malformed (leading '/', '..', etc.).

    Deliberately laxer than ``is_appdir_relative`` in ``common.url_classification``:
    this guards ``path`` parameters already known to be home-relative (file tools
    pass dirs without a trailing slash, arbitrary names, etc.), while the predicate
    detects the convention in arbitrary strings.
    """
    if path != path.strip():
        raise InvalidToolCallParameterException(
            parameter_name, f"{parameter_name} must not have leading/trailing whitespace"
        )
    if path.startswith("/"):
        raise InvalidToolCallParameterException(
            parameter_name, f"{parameter_name} must not start with '/'"
        )
    segments = path.split("/")
    if ".." in segments:
        raise InvalidToolCallParameterException(
            parameter_name, f"{parameter_name} must not contain '..'"
        )
    # Trailing '' (caused by a trailing '/') is allowed to denote a folder URL.
    if "" in segments[:-1]:
        raise InvalidToolCallParameterException(
            parameter_name, f"{parameter_name} must not contain empty segments"
        )


@inject
class HomePathResolver:
    """Resolves agent-home-relative paths to absolute DIAL file URLs and back.

    The agent home is the project's ``artifacts/`` folder in a project chat (shared by every
    chat and app of the project; ``agent_home_dir`` is ignored there), and
    ``files/{appdata}/{agent_home_dir}`` otherwise. It is resolved once per request (outside
    a project it may require a ``my_appdata_home()`` API call) and cached. Shared by the file
    tools, the path-argument transformer, and any other agent-home consumer so the home is
    resolved a single time per request.

    Absolute URLs (``files/...`` and ``projects/...``, see ``is_absolute``) come back
    unchanged: which of them a caller may use is not decided here (see
    ``current_project_url`` and ``RoutedFileStorage``).
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

    def is_absolute(self, path: str) -> bool:
        """Whether ``path`` is an absolute DIAL URL (``files/...`` or ``projects/...``) rather
        than a path relative to the agent home. Like ``files``, ``projects`` is a Core resource
        type, so a home folder of that name can't be addressed by a relative path."""
        return is_dial_storage_path(path)

    async def resolve_write_url(self, parameter_name: str, path: str) -> str:
        """Resolve a write target: only a path under the agent home is accepted, so files
        outside it, the project's read-only ones included, are never written. Every tool
        that writes, moves or deletes a file resolves its target here, never through
        ``resolve_appdata_url``, which also accepts absolute URLs for reads."""
        self._require_relative(parameter_name, path)
        return await self.resolve_appdata_url(path)

    def resolve_handoff_url(self, parameter_name: str, url: str) -> str:
        """Check a DIAL URL that QuickApps passes on to another service (an MCP grant, an
        attachment). The receiver reads it with its own grant, not through
        ``ProjectFileStorage``, so a ``projects/...`` URL is accepted only where the agent may
        read (``ProjectContext.can_read``) and comes back canonical. Any other URL comes back
        unchanged. Takes the relative form, like ``ProjectContext.contains``."""
        if not url.startswith("projects/"):
            return url
        if self._project is None or not self._project.can_read(url):
            raise InvalidToolCallParameterException(
                parameter_name,
                f"{parameter_name} accepts a projects/... URL only under the current project's "
                "context/ or artifacts/ folder",
            )
        return canonical_url(url)

    def _require_relative(self, parameter_name: str, path: str) -> None:
        if self.is_absolute(path):
            raise InvalidToolCallParameterException(
                parameter_name,
                f"{parameter_name} must be a relative path, resolved under the agent home "
                "(e.g. 'report.md' or 'docs/notes.md'), not an absolute files/... or "
                "projects/... URL",
            )

    async def resolve_appdata_url(self, path: str, parameter_name: str = "path") -> str:
        """The DIAL URL for ``path``: a relative path resolves under the agent home, and
        ``files/...`` and ``projects/...`` come back unchanged. ``parameter_name`` names the
        caller's tool parameter in the errors."""
        if not isinstance(path, str) or path == "":
            raise InvalidToolCallParameterException(
                parameter_name, f"{parameter_name} must be a non-empty string"
            )
        if "\n" in path or "\r" in path:
            raise InvalidToolCallParameterException(
                parameter_name, f"{parameter_name} must not contain newline characters"
            )
        if self.is_absolute(path):
            return path
        _validate_relative_path(path, parameter_name)
        if self._project is not None and has_unsafe_segments(path):
            # The project storage and Core decode each segment: `%2e%2e` or an encoded `/`
            # would turn into a real `..` or `/` there.
            raise InvalidToolCallParameterException(
                parameter_name,
                f"{parameter_name} must not contain '.', '..' or empty segments, or an "
                "encoded '/'",
            )
        # Spelled as given: Core accepts either spelling, and code that compares URLs
        # compares them in canonical form.
        return f"{await self.resolve_home_dir()}{path}"

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
            # The home is canonical; the model may spell the URL decoded (``My Project``).
            # Shown decoded: Core accepts that spelling when the model passes it back.
            url = canonical_url(url)
            return readable_url(url[len(home) :] if url.startswith(home) else url)
        if url.startswith(home):
            return url[len(home) :]
        return url
