from injector import inject
from pydantic import BaseModel, ConfigDict

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.exceptions import SkillInitializationException
from quickapp.skills._skill_metadata import SkillMetadata
from quickapp.skills._xml import generate_skills_xml
from quickapp.skills.skill_source import ResolvedSkillCandidate, SkillSource


class _MergedSkills(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    xml: str
    entries: dict[str, ResolvedSkillCandidate]


@inject
class SkillsRegistry(PromptPartProvider):
    """Request-scoped registry that merges every ``SkillSource`` into a single
    ``<available_skills>`` XML block.

    No I/O during merge — sources are populated by their own initializers
    beforehand; ``get_prompt_part()`` runs a pure in-memory merge and caches
    it. Reading a bundled file is the lazy exception, via ``read_skill_file``.

    Precedence is fixed by ``SkillSource.order`` (lower wins), not by DI
    module registration order. A name collision produces one unified
    exception message naming the winning source's ``display_name``,
    reported back to the losing candidate's own source via
    ``report_exceptions``.
    """

    def __init__(self, sources: list[SkillSource]) -> None:
        self._sources = sorted(sources, key=lambda s: s.order)
        self._merged: _MergedSkills | None = None

    def _get_merged(self) -> _MergedSkills:
        if self._merged is not None:
            return self._merged

        taken: dict[str, SkillSource] = {}
        merged_skills: list[SkillMetadata] = []
        entries: dict[str, ResolvedSkillCandidate] = {}

        for source in self._sources:
            collisions: list[SkillInitializationException] = []
            for candidate in source.get_candidates():
                name = candidate.metadata.name
                winner = taken.get(name)
                if winner is not None:
                    collisions.append(
                        SkillInitializationException(
                            url=candidate.url,
                            reason=(
                                f"Skill '{name}' is already provided by"
                                f" {winner.display_name}; this definition is ignored."
                            ),
                        )
                    )
                    continue
                taken[name] = source
                merged_skills.append(candidate.metadata)
                entries[name] = candidate
            if collisions:
                source.report_exceptions(collisions)

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
        """Content of a file bundled with *skill_name*, delegated to the candidate."""
        merged = self._get_merged()
        entry = merged.entries.get(skill_name)
        if entry is None:
            raise FileNotFoundError(f"Skill not found: {skill_name}")

        return await entry.read_file(file_path)
