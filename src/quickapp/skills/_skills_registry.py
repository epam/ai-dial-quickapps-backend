from __future__ import annotations

from injector import inject

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.exceptions import SkillInitializationException
from quickapp.dial_prompt_skills._dial_prompt_skills_context import _DialPromptSkillsContext
from quickapp.skills._xml import generate_skills_xml
from quickapp.skills.agent_skills_provider import AgentSkillsProvider


@inject
class SkillsRegistry(PromptPartProvider):
    """Request-scoped registry that merges predefined and DIAL-prompt skills
    into a single ``<available_skills>`` XML block.

    The registry performs **no I/O** — by contract the DIAL-prompt skill
    context is populated by ``_DialPromptSkillInitializer`` during the
    initialization phase, before message transformation runs. On the first
    ``get_prompt_part()`` call the registry merges the two ready data sources
    and caches the result for the rest of the request.

    Predefined-vs-external name collisions are reported back to the context
    as ``SkillInitializationException`` entries, so they surface in the
    unified "Initialization issues" stage alongside per-URL and catastrophic
    skill-loading failures.
    """

    def __init__(
        self,
        predefined_provider: AgentSkillsProvider,
        dial_prompt_skills_context: _DialPromptSkillsContext | None = None,
    ) -> None:
        self._predefined_provider = predefined_provider
        self._context = dial_prompt_skills_context
        self._merged: bool = False
        self._xml_cache: str = ""
        self._all_contents: dict[str, str] = {}

    def _merge(self) -> None:
        if self._merged:
            return

        predefined_skills = list(self._predefined_provider.get_all_skills())
        merged_contents = dict(self._predefined_provider.get_all_skill_contents())
        predefined_names = {s.name for s in predefined_skills}

        merged_skills = list(predefined_skills)

        if self._context is not None:
            for skill in self._context.resolved_skills:
                if skill.metadata.name in predefined_names:
                    self._context.append_exception(
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
                merged_contents[skill.metadata.name] = skill.content

        self._all_contents = merged_contents
        self._xml_cache = generate_skills_xml(merged_skills)
        self._merged = True

    async def get_prompt_part(self) -> str:
        """Return merged skills XML for inclusion in the system prompt.

        ``async`` to match the ``PromptPartProvider`` ABC; the body does no
        I/O and no ``await`` — the skill data is already loaded.
        """
        self._merge()
        return self._xml_cache

    def get_skill_content(self, skill_name: str) -> str:
        """Return the full content of a skill by name.

        Synchronous — pure dict lookup over predefined + context content.
        Raises ``FileNotFoundError`` if the skill is not in the merged set.
        """
        self._merge()
        try:
            return self._all_contents[skill_name]
        except KeyError:
            raise FileNotFoundError(f"Skill not found: {skill_name}")
