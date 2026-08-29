from quickapp.skills._exceptions import SkillFileNotFound
from quickapp.skills._skill import Skill, SkillFileContent, SkillFileEntry, SkillSourceKind
from quickapp.skills._skill_metadata import SkillMetadata


class _DialPromptSkill(Skill):
    """A skill sourced from a DIAL prompt — a single text blob, by construction.

    A prompt has no file tree, so this is the one implementation whose
    inventory is always empty and whose ``read_file`` always fails. That is a
    property of the deprecated source, not a gap: ``dial-skill`` is where
    bundled files live.
    """

    def __init__(
        self,
        metadata: SkillMetadata,
        content: str,
        url: str,
        config_index: int,
    ) -> None:
        super().__init__(
            metadata=metadata,
            source=SkillSourceKind.DIAL_PROMPT,
            url=url,
            config_index=config_index,
        )
        self._content = content

    def read_manifest(self) -> str:
        return self._content

    def list_files(self) -> list[SkillFileEntry]:
        return []

    async def read_file(self, relative_path: str) -> SkillFileContent:
        raise SkillFileNotFound(
            f"Skill '{self.metadata.name}' comes from a DIAL prompt and bundles no files;"
            " read it without a file_path"
        )
