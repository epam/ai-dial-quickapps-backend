import logging
from typing import Annotated
from urllib.parse import quote, unquote

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from quickapp.common._di_types import ForwardedHeaders

logger = logging.getLogger(__name__)

# DIAL Chat sends this header on every model call of a project chat:
# `projects/{bucket}/{path}`, spaces literal, non-ASCII bytes and `%` percent-encoded.
PROJECT_HEADER = "x-project-id"

_PROJECTS_TYPE = "projects"
_FORBIDDEN_PROJECT_SEGMENTS = frozenset({"", ".", "..", "files"})
_TRAVERSAL_SEGMENTS = frozenset({"", ".", ".."})


def canonical_resource_url(url: str) -> str:
    """``url`` with every segment percent-decoded, then re-encoded the way Core returns URLs.

    ``My Project`` and ``My%20Project`` give the same result.
    """
    return "/".join(quote(unquote(segment), safe="") for segment in url.split("/"))


def has_unsafe_segments(url: str) -> bool:
    """Whether ``url`` has an empty, ``.`` or ``..`` segment (decoded, so ``%2e%2e`` counts),
    or a segment with an encoded ``/``. A trailing ``/`` (a folder) is allowed."""
    segments = url.split("/")
    if segments and segments[-1] == "":
        segments = segments[:-1]
    return any(
        unquote(segment) in _TRAVERSAL_SEGMENTS or "/" in unquote(segment) for segment in segments
    )


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
    """``projects/{bucket}/{path}``, canonical (see ``canonical_resource_url``), no trailing
    slash."""

    @field_validator("url")
    @classmethod
    def _canonicalize(cls, value: str) -> str:
        segments = [unquote(segment) for segment in value.strip().rstrip("/").split("/")]
        if len(segments) < 3 or segments[0] != _PROJECTS_TYPE:
            raise ValueError("project url must look like projects/{bucket}/{path}")
        if any(
            segment in _FORBIDDEN_PROJECT_SEGMENTS or "/" in segment for segment in segments[1:]
        ):
            raise ValueError("project url has an invalid path segment")
        return "/".join(quote(segment, safe="") for segment in segments)

    @property
    def _content_root(self) -> str:
        return f"{self.url}/files/"

    def contains(self, url: str) -> bool:
        """Whether ``url`` is a file or folder of this project.

        Compared on the canonical form. A URL with an empty, ``.`` or ``..`` segment
        (``%2e%2e`` included) is never contained, so it can't escape the project.
        """
        if has_unsafe_segments(url):
            return False
        return canonical_resource_url(url).startswith(self._content_root)

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
    value = next(
        (v for k, v in (headers or {}).items() if k.lower() == PROJECT_HEADER and v),
        None,
    )
    if value is None:
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
