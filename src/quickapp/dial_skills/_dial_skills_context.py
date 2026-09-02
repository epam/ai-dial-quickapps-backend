import threading

from quickapp.common.exceptions import InitializationException, SkillInitializationException
from quickapp.dial_skills._dial_skill_resolver import ResolvedDialSkill


class _DialSkillsContext:
    """Request-scoped bag of state populated by ``_DialSkillInitializer`` and
    consumed by ``SkillsRegistry``.

    Mirrors ``_DialPromptSkillsContext`` in shape: resolved skills and
    initialization issues, nothing else. It does no I/O.
    """

    def __init__(self) -> None:
        self._resolved_skills: list[ResolvedDialSkill] = []
        self._exceptions: list[InitializationException] = []
        self._lock = threading.Lock()

    @property
    def resolved_skills(self) -> list[ResolvedDialSkill]:
        return self._resolved_skills

    @property
    def exceptions(self) -> list[InitializationException]:
        return self._exceptions

    def extend_resolved_skills(self, skills: list[ResolvedDialSkill]) -> None:
        with self._lock:
            self._resolved_skills.extend(skills)

    def append_exception(self, exception: SkillInitializationException) -> None:
        with self._lock:
            self._exceptions.append(exception)

    def extend_exceptions(self, exceptions: list[SkillInitializationException]) -> None:
        with self._lock:
            self._exceptions.extend(exceptions)
