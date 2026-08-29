from collections.abc import Sequence

from quickapp.common.exceptions import InitializationException
from quickapp.skills._skill import Skill


class SkillSourceContext:
    """Request-scoped bag holding one skill source's output.

    Each source package binds its own subclass so injector can tell them apart,
    and its module contributes the contents to the source-neutral
    ``list[Skill]`` and ``list[InitializationException]`` multiproviders.
    Nothing outside a source package needs to know its context exists.

    Not locked: these are request-scoped and populated from a single event-loop
    task, so there is no thread to race against.
    """

    def __init__(self) -> None:
        self._resolved_skills: list[Skill] = []
        self._exceptions: list[InitializationException] = []

    @property
    def resolved_skills(self) -> list[Skill]:
        return self._resolved_skills

    @property
    def exceptions(self) -> list[InitializationException]:
        return self._exceptions

    def extend_resolved_skills(self, skills: Sequence[Skill]) -> None:
        self._resolved_skills.extend(skills)

    def append_exception(self, exception: InitializationException) -> None:
        self._exceptions.append(exception)

    def extend_exceptions(self, exceptions: Sequence[InitializationException]) -> None:
        self._exceptions.extend(exceptions)
