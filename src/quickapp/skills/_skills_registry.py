from injector import inject
from pydantic import BaseModel, ConfigDict

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.exceptions import SkillInitializationException
from quickapp.dial_prompt_skills._dial_prompt_skills_context import _DialPromptSkillsContext
from quickapp.dial_skills._dial_skill_resolver import ResolvedDialSkill
from quickapp.dial_skills._dial_skills_client import MANIFEST_NAME
from quickapp.dial_skills._dial_skills_context import _DialSkillsContext
from quickapp.skills._exceptions import SkillFileNotFoundError, SkillFilesNotSupportedError
from quickapp.skills._xml import generate_skills_xml
from quickapp.skills.agent_skills_provider import AgentSkillsProvider


class _MergedSkills(BaseModel):
    model_config = ConfigDict(frozen=True)

    xml: str
    contents: dict[str, str]
    dial_skills: dict[str, ResolvedDialSkill]


@inject
class SkillsRegistry(PromptPartProvider):
    """Request-scoped registry that merges predefined, DIAL-prompt and
    DIAL-skill sources into a single ``<available_skills>`` XML block.

    By contract the external skill contexts are populated by their initializers
    during the initialization phase, so this class does **no I/O** while
    merging: the first ``get_prompt_part()`` call runs a pure in-memory merge
    and caches the result for the rest of the request. Reading a *bundled file*
    of a DIAL skill is the one exception — that is lazy by design and goes
    through ``read_skill_file``.

    Precedence is **predefined > dial-prompt > dial-skill**, and first
    configured wins within a source. A skill that loses a name collision is
    reported back to its own context as a ``SkillInitializationException``, so
    it surfaces in the unified "Initialization issues" stage alongside per-URL
    and catastrophic failures.
    """

    def __init__(
        self,
        predefined_provider: AgentSkillsProvider,
        dial_prompt_skills_context: _DialPromptSkillsContext | None = None,
        dial_skills_context: _DialSkillsContext | None = None,
    ) -> None:
        self._predefined_provider = predefined_provider
        self._context = dial_prompt_skills_context
        self._dial_skills_context = dial_skills_context
        self._merged: _MergedSkills | None = None

    def _get_merged(self) -> _MergedSkills:
        if self._merged is not None:
            return self._merged

        predefined_skills = list(self._predefined_provider.get_all_skills())
        contents = dict(self._predefined_provider.get_all_skill_contents())
        taken_names = {s.name for s in predefined_skills}
        merged_skills = list(predefined_skills)
        dial_skills: dict[str, ResolvedDialSkill] = {}

        if self._context is not None:
            collisions: list[SkillInitializationException] = []
            for skill in self._context.resolved_skills:
                if skill.metadata.name in taken_names:
                    collisions.append(
                        SkillInitializationException(
                            url=skill.url,
                            reason=(
                                "Has the same name as a predefined skill;"
                                " predefined takes precedence"
                            ),
                        )
                    )
                    continue
                taken_names.add(skill.metadata.name)
                merged_skills.append(skill.metadata)
                contents[skill.metadata.name] = skill.content
            if collisions:
                self._context.extend_exceptions(collisions)

        if self._dial_skills_context is not None:
            collisions = []
            for dial_skill in self._dial_skills_context.resolved_skills:
                name = dial_skill.metadata.name
                if name in taken_names:
                    collisions.append(
                        SkillInitializationException(
                            url=dial_skill.url,
                            reason=(
                                f"Has the same name as an already loaded skill '{name}';"
                                " the earlier source takes precedence"
                            ),
                        )
                    )
                    continue
                taken_names.add(name)
                merged_skills.append(dial_skill.metadata)
                contents[name] = dial_skill.content
                dial_skills[name] = dial_skill
            if collisions:
                self._dial_skills_context.extend_exceptions(collisions)

        self._merged = _MergedSkills(
            xml=generate_skills_xml(merged_skills),
            contents=contents,
            dial_skills=dial_skills,
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
            return self._get_merged().contents[skill_name]
        except KeyError:
            raise FileNotFoundError(f"Skill not found: {skill_name}")

    async def read_skill_file(self, skill_name: str, file_path: str) -> str:
        """Return the content of a file bundled with *skill_name*.

        Readability is inventory membership: a path is served only if it was
        advertised in the skill's ``<skill_files>`` block. That single check
        also covers traversal, encoded separators and hidden files — the model
        can only ask for what it was told exists.
        """
        merged = self._get_merged()
        if skill_name not in merged.contents:
            raise FileNotFoundError(f"Skill not found: {skill_name}")

        # A dial skill only reaches the merged set through the context, so the
        # two are absent together; checking both here narrows the type as well.
        context = self._dial_skills_context
        dial_skill = merged.dial_skills.get(skill_name)
        if dial_skill is None or context is None:
            raise SkillFilesNotSupportedError(skill_name)

        normalized = self._normalize_file_path(file_path)
        if normalized == MANIFEST_NAME:
            # The manifest is not in the inventory; serve what read_skill would.
            return merged.contents[skill_name]
        if normalized not in dial_skill.files:
            raise SkillFileNotFoundError(skill_name, file_path, dial_skill.files)

        return await context.read_file(dial_skill.url, normalized)

    @staticmethod
    def _normalize_file_path(file_path: str) -> str:
        """Strip the decorations a model tends to add around a listed path."""
        return file_path.strip().lstrip("/").removeprefix("./")
