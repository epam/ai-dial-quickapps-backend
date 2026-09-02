from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from quickapp.common.exceptions import SkillInitializationException
from quickapp.skills._skill_metadata import SkillMetadata


class ResolvedSkillCandidate(BaseModel):
    """One skill a ``SkillSource`` offers into the merge.

    Deliberately independent of any source's internal resolved-skill type
    (``ResolvedDialSkill``, ``ResolvedDialPromptSkill``, ...) — this is the
    only shape ``SkillsRegistry`` ever sees.

    ``read_file`` is ``None`` for sources with no bundled-file capability
    (predefined, dial-prompt); ``SkillsRegistry.read_skill_file`` raises
    ``SkillFilesNotSupportedError`` when it's ``None`` — the source decides
    that structurally (by never setting it), so the registry never needs an
    isinstance/"does this source support files" check.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    url: str
    metadata: SkillMetadata
    content: str
    read_file: Callable[[str], Awaitable[str]] | None = None


class SkillSource(ABC):
    """One contributor to the merged ``<available_skills>`` set.

    Implementations expose already-resolved skills — no I/O happens here; that
    ran during the initializer phase (mirrors the contract already documented
    on ``SkillsRegistry``). ``SkillsRegistry`` arbitrates precedence across
    sources using ``order`` and reports a losing candidate's collision back to
    its own source via ``report_exceptions`` — the message text itself is the
    registry's job (one unified format naming the winner by its
    ``display_name``), not the source's.
    """

    @property
    @abstractmethod
    def order(self) -> int:
        """Lower values win a name collision.

        A real ``@property`` (not a bare annotation) so ``ABCMeta`` actually
        refuses to instantiate a subclass that forgets to set it — a plain
        class attribute in a concrete adapter (e.g. ``order = 0``) still
        satisfies this abstract property, so adapters read no differently.
        No shared enum: picking the literal is each implementation's own
        decision; the ABC only enforces that one exists, so
        ``SkillsRegistry`` can sort deterministically regardless of DI
        module registration order.
        """
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable label used only in a collision message for some
        *other*, later source's losing candidate — e.g. ``"predefined
        skills"``. Never a Python class/type name: this is user-visible text
        rendered in the "Initialization issues" stage, not a debugging aid.
        """
        ...

    @abstractmethod
    def get_candidates(self) -> list[ResolvedSkillCandidate]: ...

    @abstractmethod
    def report_exceptions(self, exceptions: list[SkillInitializationException]) -> None:
        """Report this source's own candidates that lost a name collision.

        Called at most once per request, after the merge, with only the
        exceptions attributable to this source (message text already filled
        in by the registry). Sources that can never lose (nothing can
        outrank them — e.g. predefined) may no-op.
        """
        ...
