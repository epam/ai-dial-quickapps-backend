import logging
import sys
from typing import NamedTuple

from injector import ProviderOf, inject

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.exceptions import SkillInitializationException
from quickapp.skills._exceptions import SkillFileNotFound
from quickapp.skills._skill import Skill, SkillSourceKind
from quickapp.skills._skills_context import _SkillsContext
from quickapp.skills._xml import generate_skills_xml

logger = logging.getLogger(__name__)


def _config_order(skill: Skill) -> int:
    """Sort key for configured skills. A configured skill always carries an
    index; the fallback keeps an index-less one last instead of breaking the sort."""
    return sys.maxsize if skill.config_index is None else skill.config_index


class _MergedSkills(NamedTuple):
    xml: str
    skills: dict[str, Skill]


@inject
class SkillsRegistry(PromptPartProvider):
    """Request-scoped registry that merges every skill source into a single
    ``<available_skills>`` XML block, and the sole owner of precedence between
    them.

    By contract each source's skills are contributed by its own initializer
    during the initialization phase, so this class does **no I/O**: the first
    ``get_prompt_part()`` call runs a pure in-memory merge and caches the result
    for the rest of the request.

    ``list[Skill]`` is taken through ``ProviderOf`` rather than injected
    directly: injector concatenates the contributed lists into a *new* list at
    resolution time, so a plain ``list[Skill]`` parameter would snapshot
    whatever had been contributed when the registry was constructed.
    """

    def __init__(
        self,
        skills_provider: ProviderOf[list[Skill]],
        context: _SkillsContext,
    ) -> None:
        self._skills_provider = skills_provider
        self._context = context
        self._merged: _MergedSkills | None = None

    def _get_merged(self) -> _MergedSkills:
        if self._merged is not None:
            return self._merged

        all_skills = self._skills_provider.get()
        predefined = [s for s in all_skills if s.source is SkillSourceKind.PREDEFINED]
        configured = [s for s in all_skills if s.source is not SkillSourceKind.PREDEFINED]

        # Predefined-vs-predefined is settled upstream by `AgentSkillsProvider`
        # at startup, so predefined names arrive unique and never take part in
        # the sort below.
        merged: dict[str, Skill] = {skill.metadata.name: skill for skill in predefined}
        ordered: list[Skill] = list(predefined)
        collisions: list[SkillInitializationException] = []

        # Among configured skills the lowest config index wins, regardless of
        # type. Sorting first is what makes that deterministic across sources —
        # two independent resolvers cannot see each other, so without this the
        # winner would be decided by merge iteration order.
        for skill in sorted(configured, key=_config_order):
            name = skill.metadata.name
            winner = merged.get(name)
            if winner is None:
                merged[name] = skill
                ordered.append(skill)
                continue

            # Every loser carrying a URL is reported, so a shadowed skill is
            # never silently absent. A URL-less loser cannot be —
            # `_InitializationErrorHandler` drops a skill diagnostic with no URL
            # — but predefined skills are the only URL-less source and they
            # never lose.
            if skill.url is None:
                logger.warning(
                    "Skill '%s' from %s is shadowed by %s and has no URL to report",
                    name,
                    skill.source,
                    winner.source,
                )
                continue
            collisions.append(
                SkillInitializationException(url=skill.url, reason=self._collision_reason(winner))
            )

        if collisions:
            self._context.extend_exceptions(list(collisions))

        self._merged = _MergedSkills(
            xml=generate_skills_xml([skill.metadata for skill in ordered]),
            skills=merged,
        )
        return self._merged

    @staticmethod
    def _collision_reason(winner: Skill) -> str:
        if winner.source is SkillSourceKind.PREDEFINED:
            return "Has the same name as a predefined skill; predefined takes precedence"
        return (
            "Has the same name as an earlier configured skill;"
            " the first one in the configuration takes precedence"
        )

    async def get_prompt_part(self) -> str:
        """Return merged skills XML for inclusion in the system prompt.

        ``async`` to match ``PromptPartProvider``; body does no ``await`` — the
        skill data is already loaded.
        """
        return self._get_merged().xml

    def get_skill(self, skill_name: str) -> Skill:
        """Return one merged skill by name.

        The single accessor: callers go on to use the ``Skill`` directly, so the
        registry does not mirror its interface.

        Raises:
            SkillFileNotFound: if no source contributed that name.
        """
        try:
            return self._get_merged().skills[skill_name]
        except KeyError:
            raise SkillFileNotFound(f"Skill not found: {skill_name}")
