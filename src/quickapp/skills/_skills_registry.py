from __future__ import annotations

import logging

from injector import ProviderOf, inject

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.config.application import ApplicationConfig
from quickapp.dial_prompt_skills import DialPromptSkillResolver
from quickapp.skills._xml import generate_skills_xml
from quickapp.skills.agent_skills_provider import AgentSkillsProvider

logger = logging.getLogger(__name__)


@inject
class SkillsRegistry(PromptPartProvider):
    """Request-scoped registry that merges predefined and external skills.

    Implements ``PromptPartProvider`` — lazily fetches and merges on the first
    ``get_prompt_part()`` call, then caches for the rest of the request.
    """

    def __init__(
        self,
        predefined_provider: AgentSkillsProvider,
        config_provider: ProviderOf[ApplicationConfig],
        dial_prompt_resolver: DialPromptSkillResolver | None = None,
    ) -> None:
        self._predefined_provider = predefined_provider
        self._config_provider = config_provider
        self._dial_prompt_resolver = dial_prompt_resolver
        self._resolved: bool = False
        self._xml_cache: str = ""
        self._all_contents: dict[str, str] = {}

    async def _resolve(self) -> None:
        """Lazily resolve all skill sources. Called once per request."""
        if self._resolved:
            return

        predefined_skills = self._predefined_provider.get_all_skills()
        predefined_contents = self._predefined_provider.get_all_skill_contents()
        predefined_names = {s.name for s in predefined_skills}

        merged_skills = list(predefined_skills)
        merged_contents = dict(predefined_contents)

        if self._dial_prompt_resolver is not None:
            try:
                config = self._config_provider.get()
                skill_configs = config.skills or []
                if skill_configs:
                    resolved = await self._dial_prompt_resolver.resolve(skill_configs)
                    for metadata, content in resolved:
                        if metadata.name in predefined_names:
                            logger.warning(
                                "DIAL prompt skill '%s' has the same name as a predefined skill; "
                                "predefined takes precedence. Skipping.",
                                metadata.name,
                            )
                            continue
                        merged_skills.append(metadata)
                        merged_contents[metadata.name] = content
            except Exception:
                logger.warning(
                    "Failed to resolve DIAL prompt skills; falling back to predefined-only.",
                    exc_info=True,
                )

        self._all_contents = merged_contents
        self._xml_cache = generate_skills_xml(merged_skills)
        self._resolved = True

    async def get_prompt_part(self) -> str:
        """Return merged skills XML for inclusion in the system prompt."""
        await self._resolve()
        return self._xml_cache

    async def get_skill_content(self, skill_name: str) -> str:
        """Return the full content of a skill by name.

        Raises ``FileNotFoundError`` if the skill is not in the merged set.
        """
        await self._resolve()
        try:
            return self._all_contents[skill_name]
        except KeyError:
            raise FileNotFoundError(f"Skill not found: {skill_name}")
