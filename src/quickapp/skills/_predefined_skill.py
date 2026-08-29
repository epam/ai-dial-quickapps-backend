from quickapp.skills._exceptions import SkillFileNotFound
from quickapp.skills._skill import Skill, SkillFileContent, SkillFileEntry, SkillSourceKind
from quickapp.skills._skill_metadata import SkillMetadata
from quickapp.skills.agent_skills_provider import AgentSkillsProvider


class _PredefinedSkill(Skill):
    """A skill shipped in the image (or layered in via ``PREDEFINED_EXTRA_PATHS``).

    Manifest only for now: the predefined loader indexes ``SKILL.md`` and
    nothing beside it, so this skill bundles no readable files. Giving the
    predefined source a file tree is a separate piece of work; until then it
    reports an empty inventory rather than advertising files it cannot serve.

    Holds no state of its own — the manifest lives on the singleton
    ``AgentSkillsProvider``, because a request-scoped object cannot hold a
    process-lifetime cache.
    """

    def __init__(self, metadata: SkillMetadata, provider: AgentSkillsProvider) -> None:
        super().__init__(metadata=metadata, source=SkillSourceKind.PREDEFINED)
        self._provider = provider

    def read_manifest(self) -> str:
        return self._provider.get_skill_content(self.metadata.name)

    def list_files(self) -> list[SkillFileEntry]:
        return []

    async def read_file(self, relative_path: str) -> SkillFileContent:
        raise SkillFileNotFound(
            f"Skill '{self.metadata.name}' is a predefined skill and bundles no files;"
            " read it without a file_path"
        )
