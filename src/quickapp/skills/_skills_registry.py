from injector import inject
from pydantic import BaseModel, ConfigDict

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.exceptions import InitializationException, SkillInitializationException
from quickapp.skills._skill_metadata import SkillMetadata
from quickapp.skills._xml import generate_skills_xml
from quickapp.skills.skills_provider import ResolvedSkill, SkillsProvider


class _MergedSkills(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    xml: str
    entries: dict[str, ResolvedSkill]


@inject
class SkillsRegistry(PromptPartProvider):
    """Request-scoped registry that merges every ``SkillsProvider`` into a single
    ``<available_skills>`` XML block.

    No I/O during merge — providers are populated by their own initializers
    beforehand; ``get_prompt_part()`` runs a pure in-memory merge and caches
    it. Reading a bundled file is the lazy exception, via ``read_skill_file``.

    Precedence is fixed by ``SkillsProvider.order`` (lower wins), not by DI
    module registration order. A name collision is recorded on
    ``collision_exceptions``, which ``SkillsModule`` contributes to the
    aggregated "Initialization issues" stage.
    """

    def __init__(self, providers: list[SkillsProvider]) -> None:
        self._providers = sorted(providers, key=lambda p: p.order)
        self._collisions: list[InitializationException] = []
        self._merged: _MergedSkills | None = None

    @property
    def collision_exceptions(self) -> list[InitializationException]:
        """Name collisions found during the merge, reported as initialization issues."""
        return self._collisions

    def _get_merged(self) -> _MergedSkills:
        if self._merged is not None:
            return self._merged

        taken: dict[str, SkillsProvider] = {}
        merged_skills: list[SkillMetadata] = []
        entries: dict[str, ResolvedSkill] = {}

        for provider in self._providers:
            for skill in provider.resolved_skills:
                name = skill.metadata.name
                winner = taken.get(name)
                if winner is not None:
                    self._collisions.append(
                        SkillInitializationException(
                            url=skill.url,
                            reason=(
                                f"Skill '{name}' is already provided by"
                                f" {winner.display_name}; this definition is ignored."
                            ),
                        )
                    )
                    continue
                taken[name] = provider
                merged_skills.append(skill.metadata)
                entries[name] = skill

        self._merged = _MergedSkills(
            xml=generate_skills_xml(merged_skills),
            entries=entries,
        )
        return self._merged

    async def get_prompt_part(self) -> str:
        """Merged skills XML for the system prompt."""
        return self._get_merged().xml

    def get_skill_content(self, skill_name: str) -> str:
        """Full content of a skill by name. Raises ``FileNotFoundError`` if unknown."""
        try:
            return self._get_merged().entries[skill_name].content
        except KeyError:
            raise FileNotFoundError(f"Skill not found: {skill_name}")

    async def read_skill_file(self, skill_name: str, file_path: str) -> str:
        """Content of a file bundled with *skill_name*, delegated to the skill."""
        merged = self._get_merged()
        skill = merged.entries.get(skill_name)
        if skill is None:
            raise FileNotFoundError(f"Skill not found: {skill_name}")

        return await skill.read_file(file_path)
