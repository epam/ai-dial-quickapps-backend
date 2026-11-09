import logging
from typing import Annotated
from urllib.parse import unquote

from aidial_client import InvalidDialURLError
from aidial_client.helpers.storage_resource import split_relative_segments
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from quickapp.common._di_types import ForwardedHeaders
from quickapp.common.utils import canonical_url

logger = logging.getLogger(__name__)

# DIAL Chat sends this header on every model call of a project chat:
# `projects/{bucket}/{path}`, spaces literal, non-ASCII bytes and `%` percent-encoded.
PROJECT_HEADER = "x-project-id"

_PROJECTS_TYPE = "projects"
_FORBIDDEN_PROJECT_SEGMENTS = frozenset({"", ".", "..", "files"})


def has_unsafe_segments(url: str) -> bool:
    """Whether ``url`` has an empty, ``.`` or ``..`` segment (decoded, so ``%2e%2e`` counts),
    or a segment with an encoded ``/``. A trailing ``/`` (a folder) is allowed."""
    try:
        split_relative_segments(url, "url", allow_trailing_slash=True)
    except InvalidDialURLError:
        return True
    return False


class ProjectContext(BaseModel):
    """The project a request belongs to, and the project layout shared by Chat and the apps.

    All project content lives under Core's ``{url}/files/``:

    - ``PROJECT.md``: YAML frontmatter + the project instructions as the body;
    - ``context/``: the user's context files;
    - ``conversations/``: the project's chats, written by Chat only;
    - ``artifacts/``: files produced for the user (shown by Chat as the project's Outputs).
    """

    model_config = ConfigDict(frozen=True)

    url: str
    """``projects/{bucket}/{path}``, canonical (each segment percent-encoded, see
    ``canonical_url``), no trailing slash."""

    @field_validator("url")
    @classmethod
    def _canonicalize(cls, value: str) -> str:
        raw = value.strip().rstrip("/")
        segments = [unquote(segment) for segment in raw.split("/")]
        if len(segments) < 3 or segments[0] != _PROJECTS_TYPE:
            raise ValueError("project url must look like projects/{bucket}/{path}")
        if any(
            segment in _FORBIDDEN_PROJECT_SEGMENTS or "/" in segment for segment in segments[1:]
        ):
            raise ValueError("project url has an invalid path segment")
        # Chat sends spaces literal, Core returns them as %20: compare one encoded form.
        return canonical_url(raw)

    @property
    def _content_root(self) -> str:
        return f"{self.url}/files/"

    def contains(self, url: str) -> bool:
        """Whether ``url`` is a file or folder of this project.

        Compared on the canonical form. A URL with an empty, ``.`` or ``..`` segment
        (``%2e%2e`` included) is never contained, so it can't escape the project.

        Relative form only: an absolute Core URL (``{DIAL_URL}/v1/projects/...``) is not
        contained and keeps today's v1 path. Every caller (file tools, ``web_fetch``, the file
        loader, ``DialFileService``, ``DialDownloader``) gets agent paths or Core-listed
        URLs, which are relative; the v2 client builds ``v2/{url}`` from the relative form.
        """
        if has_unsafe_segments(url):
            return False
        return canonical_url(url).startswith(self._content_root)

    @property
    def instructions_url(self) -> str:
        return f"{self._content_root}PROJECT.md"

    @property
    def context_root(self) -> str:
        return f"{self._content_root}context/"

    @property
    def artifacts_root(self) -> str:
        return f"{self._content_root}artifacts/"


def extract_project_context(headers: ForwardedHeaders) -> "ProjectContext | None":
    """The project named by the ``x-project-id`` header, or ``None``.

    A malformed header is ignored with a WARNING (without the value): the request runs
    without a project.
    """
    value = {k.lower(): v for k, v in (headers or {}).items()}.get(PROJECT_HEADER)
    if not value:
        return None
    try:
        return ProjectContext(url=value)
    except ValidationError:
        logger.warning(
            "Ignoring a malformed %s header: the request runs without a project", PROJECT_HEADER
        )
        return None


# `None` outside a project, or when preview features are off.
PROJECT_CONTEXT = Annotated[ProjectContext | None, "PROJECT_CONTEXT"]
