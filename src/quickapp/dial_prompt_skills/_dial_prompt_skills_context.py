import threading

from quickapp.common.exceptions import InitializationException, SkillInitializationException
from quickapp.skills import ResolvedSkill, SkillsProvider


class _DialPromptSkillsContext(SkillsProvider):
    """Request-scoped bag of state populated by ``_DialPromptSkillInitializer``
    and the ``SkillsProvider`` ``SkillsRegistry`` consumes for it.

    Mirrors ``_MCPToolingContext`` in spirit but is a standalone class — the
    ``ToolingContextBase._tools`` field name does not fit the skills domain.
    Prompt skills are single-document, so their skills carry no ``reader``.
    """

    order = 10
    display_name = "DIAL prompt skills"

    def __init__(self) -> None:
        self._resolved_skills: list[ResolvedSkill] = []
        self._exceptions: list[InitializationException] = []
        self._lock = threading.Lock()

    @property
    def resolved_skills(self) -> list[ResolvedSkill]:
        return self._resolved_skills

    @property
    def exceptions(self) -> list[InitializationException]:
        return self._exceptions

    def extend_resolved_skills(self, skills: list[ResolvedSkill]) -> None:
        with self._lock:
            self._resolved_skills.extend(skills)

    def append_exception(self, exception: SkillInitializationException) -> None:
        with self._lock:
            self._exceptions.append(exception)

    def extend_exceptions(self, exceptions: list[SkillInitializationException]) -> None:
        with self._lock:
            self._exceptions.extend(exceptions)
