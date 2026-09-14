import threading

from quickapp.common.exceptions import InitializationException, SkillInitializationException
from quickapp.skills import ResolvedSkill, SkillsProvider

_USER_SELECTED_HEADER = "Skill `{name}`, selected by the user for this conversation."


def _mark_user_selected(skill: ResolvedSkill) -> ResolvedSkill:
    """Prepend one line naming the skill as user-selected, so the model can tell it
    apart from the agent's own when the user refers to it in words."""
    header = _USER_SELECTED_HEADER.format(name=skill.metadata.name)
    return skill.model_copy(update={"content": f"{header}\n{skill.content}"})


class _InvokedSkillsContext(SkillsProvider):
    """Request-scoped bag of the skills picked on this conversation's messages,
    populated by ``_SkillInvocationInitializer``, and the ``SkillsProvider``
    ``SkillsRegistry`` consumes for them.

    The entries are the skills as resolved — own name, own description, real URL,
    files and reader — so everything downstream (the merge, ``generate_skills_xml``,
    ``read_skill``, bundled files) works unchanged.

    ``order`` runs ahead of every agent source (agent/predefined ``0``, dial-prompt
    ``10``, dial-skill ``20``), so a picked skill wins a name collision and the
    agent's same-named skill is dropped by the registry's collision path.
    """

    order = -10
    display_name = "user skills"

    def __init__(self) -> None:
        self._current_pick_url: str | None = None
        self._skills_by_url: dict[str, ResolvedSkill] = {}
        self._exceptions: list[InitializationException] = []
        self._lock = threading.Lock()

    @property
    def resolved_skills(self) -> list[ResolvedSkill]:
        return list(self._skills_by_url.values())

    @property
    def exceptions(self) -> list[InitializationException]:
        return self._exceptions

    @property
    def current_pick_url(self) -> str | None:
        """The pick on the message being answered, if this turn made one.

        Recorded here rather than re-parsed from the messages later, so the injector
        does not care whether the scrub transformer has already run.
        """
        return self._current_pick_url

    def set_current_pick_url(self, url: str | None) -> None:
        self._current_pick_url = url

    def set_resolved_skills(self, skills: list[ResolvedSkill]) -> None:
        with self._lock:
            self._skills_by_url = {skill.url: _mark_user_selected(skill) for skill in skills}

    def find_skill(self, url: str) -> ResolvedSkill | None:
        """The skill resolved for *url*, or ``None`` if it failed or was over the cap."""
        return self._skills_by_url.get(url)

    def append_exception(self, exception: SkillInitializationException) -> None:
        with self._lock:
            self._exceptions.append(exception)
