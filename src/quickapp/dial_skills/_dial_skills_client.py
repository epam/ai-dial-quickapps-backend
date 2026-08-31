import logging
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote

from aidial_client import AsyncDial
from injector import inject
from pydantic import BaseModel, ConfigDict

from quickapp.dial_skills._exceptions import (
    DialSkillFileNotTextError,
    DialSkillFileReadError,
    DialSkillFileTooLargeError,
    describe_exception,
)
from quickapp.dial_skills._settings import DialSkillsSettings

logger = logging.getLogger(__name__)

MANIFEST_NAME = "SKILL.md"

# Extensions a skill may publish to the model. The same allowlist decides what is
# advertised in <skill_files> and what `read_skill` will serve, so the model can
# only ask for what it was told exists. Binary and asset files are deferred.
_TEXT_EXTENSIONS = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
        ".csv",
        ".tsv",
        ".xml",
        ".html",
        ".toml",
        ".ini",
        ".sql",
        ".py",
        ".sh",
        ".js",
        ".ts",
    }
)


class SkillInventory(BaseModel):
    """The readable files of one skill, as advertised to the model."""

    model_config = ConfigDict(frozen=True)

    files: tuple[str, ...] = ()
    truncated: bool = False


@inject
class _DialSkillsClient:
    """Read-side wrapper over DIAL Core's ``/v2/skills`` API.

    Owns the three things the resolver and the reader tool should not have to
    care about: which files a skill is allowed to publish, the byte cap on any
    single read, and the bounds on a paged listing.
    """

    def __init__(self, dial_client: AsyncDial, settings: DialSkillsSettings) -> None:
        self._dial_client = dial_client
        self._settings = settings

    @property
    def max_files(self) -> int:
        """The inventory ceiling, so callers can name it in a truncation note."""
        return self._settings.max_files

    @property
    def _skills(self) -> Any:
        """The client's ``/v2/skills`` resource."""
        return self._dial_client.skills  # type: ignore[attr-defined]

    async def read_manifest(self, url: str) -> str:
        """Read a skill's ``SKILL.md``."""
        return await self.read_text_file(url, MANIFEST_NAME)

    async def read_text_file(self, url: str, file_path: str) -> str:
        """Read one file of a skill as UTF-8 text.

        Raises ``DialSkillFileReadError`` (or a subclass) for every failure mode
        — transport, over-cap, or undecodable — so callers have one thing to
        catch and a message that always names a reason.
        """
        try:
            response = await self._skills.get_file(url, file_path)
            content = await response.aget_content()
        except Exception as exc:
            raise DialSkillFileReadError(file_path, describe_exception(exc)) from exc

        limit = self._settings.file_max_bytes
        if len(content) > limit:
            raise DialSkillFileTooLargeError(file_path, len(content), limit)

        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DialSkillFileNotTextError(file_path) from exc

    async def list_text_files(self, url: str) -> SkillInventory:
        """List the skill's readable files, relative to the skill root.

        Follows Core's continuation token, bounded by ``listing_max_pages`` and
        by a repeated-token guard: nothing above this imposes a deadline, so a
        stuck cursor must not be able to hang initialization.
        """
        paths: dict[str, None] = {}
        seen_tokens: set[str] = set()
        token: str | None = None
        truncated = False

        for _ in range(self._settings.listing_max_pages):
            page = await self._skills.list_files(url, token=token, recursive=True)
            prefix = page.url if page.url.endswith("/") else f"{page.url}/"

            for item in page.items or []:
                if len(paths) >= self._settings.max_files:
                    truncated = True
                    break
                relative = self._relative_path(item.url, prefix)
                if relative is not None and self._is_advertisable(relative):
                    paths[relative] = None

            token = page.next_token
            if truncated or not token or token in seen_tokens:
                # A replayed token means the server is not advancing; stop rather
                # than spend the page budget re-reading the same entries.
                break
            seen_tokens.add(token)
        else:
            # Ran out of the page budget with a token still pending.
            truncated = truncated or bool(token)

        return SkillInventory(files=tuple(paths), truncated=truncated)

    @staticmethod
    def _relative_path(item_url: str, prefix: str) -> str | None:
        """Convert a listing entry's url into a path relative to the skill root.

        Returns ``None`` for an entry outside the listed folder. ``removeprefix``
        is a silent no-op on a mismatch, which would advertise a full
        ``skills/<bucket>/...`` url as a path inside the skill.
        """
        if not item_url.startswith(prefix):
            logger.warning("Skipping skill file listing entry outside the listed folder")
            return None
        return unquote(item_url[len(prefix) :])

    @staticmethod
    def _is_advertisable(relative_path: str) -> bool:
        """Whether *relative_path* may be shown to, and read by, the model."""
        if not relative_path or relative_path.endswith("/"):
            # Core reports subfolders as items too; the trailing slash is the
            # only reliable signal (see SkillFileItem in aidial-client).
            return False
        if relative_path == MANIFEST_NAME:
            # Already served by read_skill without a file_path.
            return False
        segments = relative_path.split("/")
        if any(not segment or segment.startswith(".") for segment in segments):
            # Hidden entries at any depth, and Core's own .dial-resource marker.
            return False
        return PurePosixPath(relative_path).suffix.lower() in _TEXT_EXTENSIONS
