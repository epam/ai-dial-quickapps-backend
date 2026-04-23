from injector import inject
from pydantic import BaseModel, ConfigDict

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.exceptions import SkillInitializationException
from quickapp.dial_prompt_skills._dial_prompt_skills_context import _DialPromptSkillsContext
from quickapp.skills._xml import generate_skills_xml
from quickapp.skills.agent_skills_provider import AgentSkillsProvider


class _MergedSkills(BaseModel):
    model_config = ConfigDict(frozen=True)

    xml: str
    contents: dict[str, str]


@inject
class SkillsRegistry(PromptPartProvider):
    """Request-scoped registry that merges predefined and DIAL-prompt skills
    into a single ``<available_skills>`` XML block.

    By contract the DIAL-prompt skill context is populated by
    ``_DialPromptSkillInitializer`` during the initialization phase, so this
    class does **no I/O**: the first ``get_prompt_part()`` call runs a pure
    in-memory merge and caches the result for the rest of the request.

    Predefined-vs-external name collisions are reported back to the context as
    ``SkillInitializationException`` entries, so they surface in the unified
    "Initialization issues" stage alongside per-URL and catastrophic failures.
    """

    def __init__(
        self,
        predefined_provider: AgentSkillsProvider,
        dial_prompt_skills_context: _DialPromptSkillsContext | None = None,
    ) -> None:
        self._predefined_provider = predefined_provider
        self._context = dial_prompt_skills_context
        self._merged: _MergedSkills | None = None

    def _get_merged(self) -> _MergedSkills:
        if self._merged is not None:
            return self._merged

        predefined_skills = list(self._predefined_provider.get_all_skills())
        contents = dict(self._predefined_provider.get_all_skill_contents())
        predefined_names = {s.name for s in predefined_skills}
        merged_skills = list(predefined_skills)

        if self._context is not None:
            collisions: list[SkillInitializationException] = []
            for skill in self._context.resolved_skills:
                if skill.metadata.name in predefined_names:
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
                merged_skills.append(skill.metadata)
                contents[skill.metadata.name] = skill.content
            if collisions:
                self._context.extend_exceptions(collisions)

        self._merged = _MergedSkills(
            xml=generate_skills_xml(merged_skills),
            contents=contents,
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
