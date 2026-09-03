from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict

from quickapp.common.exceptions import SkillInitializationException
from quickapp.skills._exceptions import SkillFilesNotSupportedError
from quickapp.skills._skill_metadata import SkillMetadata


class SkillFileReader(ABC):
    """Reads one bundled file of a ``ResolvedSkillCandidate``.

    Implemented by sources with bundled-file capability (today, only
    ``DialSkillReader``) and stored on each of their candidates as
    ``ResolvedSkillCandidate.reader``.
    """

    @abstractmethod
    async def read_bundled_file(
        self, candidate: "ResolvedSkillCandidate", file_path: str
    ) -> str: ...


class ResolvedSkillCandidate(BaseModel):
    """One skill a ``SkillSource`` offers into the merge.

    Independent of any source's internal resolved-skill type — the only
    shape ``SkillsRegistry`` ever sees. ``reader`` is ``None`` for sources
    with no bundled-file capability; ``read_file`` raises
    ``SkillFilesNotSupportedError`` in that case.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    url: str
    metadata: SkillMetadata
    content: str
    files: tuple[str, ...] = ()
    reader: SkillFileReader | None = None

    async def read_file(self, file_path: str) -> str:
        if self.reader is None:
            raise SkillFilesNotSupportedError(self.metadata.name)
        return await self.reader.read_bundled_file(self, file_path)


class SkillSource(ABC):
    """One contributor to the merged ``<available_skills>`` set.

    No I/O here — resolution already ran during the initializer phase.
    ``SkillsRegistry`` sorts sources by ``order`` and reports a losing
    candidate's collision back to its own source via ``report_exceptions``.
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
        """Human-readable label used in a collision message for some
        *other* source's losing candidate — e.g. ``"predefined skills"``."""
        ...

    @abstractmethod
    def get_candidates(self) -> list[ResolvedSkillCandidate]: ...

    @abstractmethod
    def report_exceptions(self, exceptions: list[SkillInitializationException]) -> None:
        """Report this source's own candidates that lost a name collision.
        Sources that can never lose (e.g. predefined) may no-op."""
        ...
