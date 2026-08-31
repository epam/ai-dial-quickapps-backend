import threading

from injector import inject

from quickapp.common.exceptions import InitializationException, SkillInitializationException
from quickapp.dial_skills._dial_skill_resolver import ResolvedDialSkill
from quickapp.dial_skills._dial_skills_client import _DialSkillsClient


@inject
class _DialSkillsContext:
    """Request-scoped bag of state populated by ``_DialSkillInitializer`` and
    consumed by ``SkillsRegistry``.

    Unlike ``_DialPromptSkillsContext`` it also owns the on-demand read path:
    a skill's bundled files are fetched lazily, when the model asks for one,
    and memoized for the rest of the request so re-reading a reference costs
    nothing.
    """

    def __init__(self, client: _DialSkillsClient) -> None:
        self._client = client
        self._resolved_skills: list[ResolvedDialSkill] = []
        self._exceptions: list[InitializationException] = []
        self._file_cache: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    @property
    def resolved_skills(self) -> list[ResolvedDialSkill]:
        return self._resolved_skills

    @property
    def exceptions(self) -> list[InitializationException]:
        return self._exceptions

    def extend_resolved_skills(self, skills: list[ResolvedDialSkill]) -> None:
        with self._lock:
            self._resolved_skills.extend(skills)

    def append_exception(self, exception: SkillInitializationException) -> None:
        with self._lock:
            self._exceptions.append(exception)

    def extend_exceptions(self, exceptions: list[SkillInitializationException]) -> None:
        with self._lock:
            self._exceptions.extend(exceptions)

    async def read_file(self, url: str, file_path: str) -> str:
        """Read one bundled file, memoized per request."""
        key = (url, file_path)
        cached = self._file_cache.get(key)
        if cached is not None:
            return cached
        content = await self._client.read_text_file(url, file_path)
        self._file_cache[key] = content
        return content
