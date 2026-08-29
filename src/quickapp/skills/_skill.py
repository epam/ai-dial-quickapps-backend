from abc import ABC, abstractmethod
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from quickapp.skills._skill_metadata import SkillMetadata


class SkillSourceKind(StrEnum):
    """Where a skill came from. Carried on the ``Skill``, not on its metadata —
    ``SkillMetadata`` holds frontmatter fields only, and provenance is not one.
    """

    PREDEFINED = "predefined"
    DIAL_PROMPT = "dial-prompt"
    DIAL_SKILL = "dial-skill"


class SkillFileEntry(BaseModel):
    """One bundled file in a skill's inventory.

    A model rather than a bare ``str`` so the inventory can grow a ``size``
    field once DIAL Core carries one in its file listing.
    """

    model_config = ConfigDict(frozen=True)

    path: str
    """POSIX path relative to the skill root, e.g. ``references/api.md``."""


class SkillFileContent(BaseModel):
    """The decoded text of one skill file, as returned to the agent."""

    model_config = ConfigDict(frozen=True)

    path: str
    text: str
    content_type: str


class Skill(ABC):
    """A skill: resident metadata plus lazily readable content.

    Every implementation obeys one cost model — **metadata and the inventory
    are resident, content is not**. ``metadata`` is parsed once so the
    ``<available_skills>`` block can be built with no I/O, and ``list_files``
    is synchronous because the inventory is resolved during initialization (a
    directory walk for predefined skills, one metadata call for DIAL skills,
    empty for DIAL prompts). ``read_file`` is the only member that touches a
    file or the network, and only when the agent asks for it.

    Manifests are the one deliberate exception: they are fetched during
    initialization because the agent reads them constantly and they are the
    skill's entry point, so ``read_manifest`` is synchronous too.
    """

    def __init__(
        self,
        metadata: SkillMetadata,
        source: SkillSourceKind,
        url: str | None = None,
        config_index: int | None = None,
    ) -> None:
        self.metadata = metadata
        self.source = source
        self.url = url
        """Source URL; ``None`` for predefined skills, which have no URL."""
        self.config_index = config_index
        """Position in ``ApplicationConfig.skills``; ``None`` for predefined."""

    @abstractmethod
    def read_manifest(self) -> str:
        """Return the raw ``SKILL.md``, frontmatter included. Resident — no I/O."""

    @abstractmethod
    def list_files(self) -> list[SkillFileEntry]:
        """Return the bundled files, excluding ``SKILL.md``. Resolved at init — no I/O."""

    @property
    def inventory_truncated(self) -> bool:
        """Whether ``list_files`` is a partial view of the skill's contents.

        True only when the inventory cap stopped the walk, in which case a
        "file not found" error must say so rather than imply the skill holds
        nothing else.
        """
        return False

    @abstractmethod
    async def read_file(self, relative_path: str) -> SkillFileContent:
        """Read one bundled file.

        Raises ``SkillFileNotFound``, ``SkillFileTooLarge`` or
        ``SkillFileNotText`` — all rendered to the agent as tool-call errors.
        """
