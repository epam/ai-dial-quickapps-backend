import threading

from injector import inject

from quickapp.dial_skills._dial_skills_client import MANIFEST_NAME, _DialSkillsClient
from quickapp.skills import ResolvedSkillCandidate, SkillFileNotFoundError, SkillFileReader


def _normalize_file_path(file_path: str) -> str:
    """Strip the decorations a model tends to add around a listed path."""
    return file_path.strip().lstrip("/").removeprefix("./")


@inject
class DialSkillReader(SkillFileReader):
    """Reads one file bundled with a resolved DIAL skill candidate.

    Request-scoped; its own memoization cache lives as long as one request.
    """

    def __init__(self, client: _DialSkillsClient) -> None:
        self._client = client
        self._file_cache: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    async def read_bundled_file(self, skill: ResolvedSkillCandidate, file_path: str) -> str:
        """Read one file bundled with *skill*, honoring its inventory.

        Readability is inventory membership — covers traversal, encoded
        separators and hidden files too, since the model can only ask for
        what it was told exists.
        """
        normalized = _normalize_file_path(file_path)
        if normalized == MANIFEST_NAME:
            # The manifest is not in the inventory; serve what read_skill would.
            return skill.content
        if normalized not in skill.files:
            raise SkillFileNotFoundError(skill.metadata.name, file_path, skill.files)

        key = (skill.url, normalized)
        with self._lock:
            cached = self._file_cache.get(key)
        if cached is not None:
            return cached

        content = await self._client.read_text_file(skill.url, normalized)
        with self._lock:
            self._file_cache[key] = content
        return content
