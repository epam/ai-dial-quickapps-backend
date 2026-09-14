from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field

from quickapp.skills._exceptions import SkillFilesNotSupportedError
from quickapp.skills._skill_metadata import SkillMetadata


class SkillFileReader(ABC):
    """Reads one bundled file of a ``ResolvedSkill``.

    Implemented by sources with bundled-file capability (today, only
    ``DialSkillReader``) and stored on each skill they resolve.
    """

    @abstractmethod
    async def read_bundled_file(self, skill: "ResolvedSkill", file_path: str) -> str: ...


class ResolvedSkill(BaseModel):
    """One resolved skill, whatever produced it.

    ``reader`` is ``None`` for sources with no bundled-file capability;
    ``read_file`` raises ``SkillFilesNotSupportedError`` in that case.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    url: str
    metadata: SkillMetadata
    content: str
    files: tuple[str, ...] = ()
    warnings: list[str] = Field(default_factory=list)
    reader: SkillFileReader | None = None

    async def read_file(self, file_path: str) -> str:
        if self.reader is None:
            raise SkillFilesNotSupportedError(self.metadata.name)
        return await self.reader.read_bundled_file(self, file_path)


class SkillsProvider(ABC):
    """Contributes already-resolved skills to the merged ``<available_skills>`` set.

    No I/O here — resolution already ran during the initializer phase.
    ``SkillsRegistry`` sorts providers by ``order`` and merges their
    ``resolved_skills``.
    """

    @property
    @abstractmethod
    def order(self) -> int:
        """Lower wins a name collision. A real ``@property`` so a subclass
        that forgets to set it can't be instantiated; a plain class
        attribute (``order = 0``) still satisfies it."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable label naming this provider as the winner in a
        collision message — e.g. ``"predefined skills"``."""
        ...

    @property
    @abstractmethod
    def resolved_skills(self) -> list[ResolvedSkill]: ...
