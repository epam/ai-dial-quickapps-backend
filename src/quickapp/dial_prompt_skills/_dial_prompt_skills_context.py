import threading

from quickapp.common.exceptions import SkillInitializationException

from ._dial_prompt_skill_resolver import ResolvedDialPromptSkill


class _DialPromptSkillsContext:
    """Request-scoped bag of state populated by ``_DialPromptSkillInitializer``
    and consumed by ``SkillsRegistry`` during message finalization.

    Mirrors ``_MCPToolingContext`` in spirit but is a standalone class — the
    ``ToolingContextBase._tools`` field name does not fit the skills domain.
    """

    def __init__(self) -> None:
        self._resolved_skills: list[ResolvedDialPromptSkill] = []
        self._exceptions: list[SkillInitializationException] = []
        self._lock = threading.Lock()

    @property
    def resolved_skills(self) -> list[ResolvedDialPromptSkill]:
        return self._resolved_skills

    @property
    def exceptions(self) -> list[SkillInitializationException]:
        return self._exceptions

    def extend_resolved_skills(self, skills: list[ResolvedDialPromptSkill]) -> None:
        with self._lock:
            self._resolved_skills.extend(skills)

    def append_exception(self, exception: SkillInitializationException) -> None:
        with self._lock:
            self._exceptions.append(exception)

    def extend_exceptions(self, exceptions: list[SkillInitializationException]) -> None:
        with self._lock:
            self._exceptions.extend(exceptions)
