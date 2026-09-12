import threading

from quickapp.common.exceptions import InitializationException, SkillInitializationException
from quickapp.skills import ResolvedSkill, SkillsProvider


class _DialSkillsContext(SkillsProvider):
    """Request-scoped bag of state populated by ``_DialSkillInitializer`` and
    the ``SkillsProvider`` ``SkillsRegistry`` consumes for it.

    Mirrors ``_DialPromptSkillsContext`` in shape. It does no I/O — each
    skill already carries the reader it needs.
    """

    order = 20
    display_name = "DIAL skill resources"

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
