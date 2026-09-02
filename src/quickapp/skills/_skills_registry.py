from injector import inject
from pydantic import BaseModel, ConfigDict

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.exceptions import SkillInitializationException
from quickapp.skills._exceptions import SkillFilesNotSupportedError
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

    By contract each source's underlying context is populated by its own
    initializer during the initialization phase, so this class does **no
    I/O** while merging: the first ``get_prompt_part()`` call runs a pure
    in-memory merge and caches the result for the rest of the request.
    Reading a *bundled file* of a skill is the one exception — that is lazy
    by design and goes through ``read_skill_file``.

    Precedence across sources is fixed by each ``SkillSource.order`` (a plain
    int; lower wins), not by DI module registration order — reordering
    ``AppFactory.build_di_modules()`` cannot change behavior. Within a single
    source, first configured still wins (unchanged, source-internal dedup
    already happens in each resolver). A name collision produces one
    unified exception message naming the source that already claimed it by
    its ``display_name``, regardless of which two sources are involved. The
    exception is reported back to the losing candidate's own source via
    ``report_exceptions``, so it surfaces in the unified "Initialization
    issues" stage alongside per-URL and catastrophic failures.
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
        """Return merged skills XML for inclusion in the system prompt.

        ``async`` to match ``PromptPartProvider``; body does no ``await`` —
        the skill data is already loaded.
        """
        return self._get_merged().xml

    def get_skill_content(self, skill_name: str) -> str:
        """Return the full content of a skill by name.

        Synchronous pure dict lookup. Raises ``FileNotFoundError`` if the skill
        is not in the merged set.
        """
        try:
            return self._get_merged().entries[skill_name].content
        except KeyError:
            raise FileNotFoundError(f"Skill not found: {skill_name}")

    async def read_skill_file(self, skill_name: str, file_path: str) -> str:
        """Return the content of a file bundled with *skill_name*.

        Pure lookup plus one delegated call: which sources support bundled
        files, path normalization, and the I/O itself are all decided by
        whichever ``SkillSource`` produced this candidate — this method never
        needs to know which one that was.
        """
        merged = self._get_merged()
        entry = merged.entries.get(skill_name)
        if entry is None:
            raise FileNotFoundError(f"Skill not found: {skill_name}")

        if entry.read_file is None:
            raise SkillFilesNotSupportedError(skill_name)

        return await entry.read_file(file_path)
