from quickapp.dial_skills._dial_skills_client import DialSkillsClient
from quickapp.skills._skill import Skill, SkillFileContent, SkillFileEntry, SkillSourceKind
from quickapp.skills._skill_metadata import SkillMetadata


class _DialSkill(Skill):
    """A skill stored in DIAL Core as a ``skills/`` folder resource.

    The manifest and the inventory were fetched during initialization, so the
    only member that goes to the network is ``read_file`` — one round-trip per
    file the agent actually asks for, cached for the rest of the request. No
    cross-request cache: the natural key is the skill's aggregate etag, and
    Core does not expose one cheaply yet, so caching on a proxy signal would
    risk serving stale instructions after an edit.
    """

    def __init__(
        self,
        metadata: SkillMetadata,
        manifest: str,
        files: list[SkillFileEntry],
        url: str,
        config_index: int,
        client: DialSkillsClient,
        files_truncated: bool = False,
    ) -> None:
        super().__init__(
            metadata=metadata,
            source=SkillSourceKind.DIAL_SKILL,
            url=url,
            config_index=config_index,
        )
        # Narrower than the base's `url: str | None`, which is None only for
        # predefined skills; a DIAL skill always has one.
        self._url = url
        self._manifest = manifest
        self._files = files
        self._files_truncated = files_truncated
        self._client = client
        self._file_cache: dict[str, SkillFileContent] = {}

    def read_manifest(self) -> str:
        return self._manifest

    def list_files(self) -> list[SkillFileEntry]:
        return list(self._files)

    @property
    def inventory_truncated(self) -> bool:
        return self._files_truncated

    async def read_file(self, relative_path: str) -> SkillFileContent:
        cached = self._file_cache.get(relative_path)
        if cached is not None:
            return cached

        content = await self._client.get_file(self._url, relative_path)
        self._file_cache[relative_path] = content
        return content
