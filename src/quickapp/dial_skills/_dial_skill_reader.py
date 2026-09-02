import threading

from injector import inject

from quickapp.dial_skills._dial_skill_resolver import ResolvedDialSkill
from quickapp.dial_skills._dial_skills_client import MANIFEST_NAME, _DialSkillsClient
from quickapp.skills import SkillFileNotFoundError


def _normalize_file_path(file_path: str) -> str:
    """Strip the decorations a model tends to add around a listed path."""
    return file_path.strip().lstrip("/").removeprefix("./")


@inject
class DialSkillReader:
    """Reads one file bundled with a resolved DIAL skill.

    The one I/O operation the ``skills`` layer needs from ``dial_skills``
    beyond the merge-time state ``_DialSkillsContext`` already exposes.
    Request-scoped, so its own memoization cache lives exactly as long as one
    request needs it — nothing else reads or writes this cache, so it stays
    private here rather than in the shared context.
    """

    def __init__(self, client: _DialSkillsClient) -> None:
        self._client = client
        self._file_cache: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    async def read_bundled_file(self, skill: ResolvedDialSkill, file_path: str) -> str:
        """Read one file bundled with *skill*, honoring its inventory.

        Readability is inventory membership: a path is served only if it was
        advertised in the skill's ``<skill_files>`` block. That single check
        also covers traversal, encoded separators and hidden files — the model
        can only ask for what it was told exists. Reads are memoized for the
        rest of the request, so re-reading a reference costs nothing.
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
