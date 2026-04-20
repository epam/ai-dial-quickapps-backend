from __future__ import annotations

import asyncio

from aidial_sdk.chat_completion import Stage, Status
from injector import ProviderOf, inject

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.config.application import ApplicationConfig
from quickapp.dial_prompt_skills import DialPromptSkillResolver
from quickapp.skills._exceptions import SkillResolutionWarning
from quickapp.skills._xml import generate_skills_xml
from quickapp.skills.agent_skills_provider import AgentSkillsProvider


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
        stage_provider: ProviderOf[Stage],
        dial_prompt_resolver: DialPromptSkillResolver | None = None,
    ) -> None:
        self._predefined_provider = predefined_provider
        self._config_provider = config_provider
        self._stage_provider = stage_provider
        self._dial_prompt_resolver = dial_prompt_resolver
        self._resolved: bool = False
        self._resolve_lock = asyncio.Lock()
        self._xml_cache: str = ""
        self._all_contents: dict[str, str] = {}

    async def _resolve(self) -> None:
        """Lazily resolve all skill sources. Called once per request."""
        if self._resolved:
            return
        async with self._resolve_lock:
            if self._resolved:
                return

            predefined_skills = self._predefined_provider.get_all_skills()
            predefined_contents = self._predefined_provider.get_all_skill_contents()
            predefined_names = {s.name for s in predefined_skills}

            merged_skills = list(predefined_skills)
            merged_contents = dict(predefined_contents)
            warnings: list[SkillResolutionWarning] = []
            catastrophic_reason: str | None = None

            if self._dial_prompt_resolver is not None:
                try:
                    config = self._config_provider.get()
                    skill_configs = config.skills or []
                    if skill_configs:
                        resolved, resolver_warnings = await self._dial_prompt_resolver.resolve(
                            skill_configs
                        )
                        warnings.extend(resolver_warnings)
                        for skill in resolved:
                            if skill.metadata.name in predefined_names:
                                warnings.append(
                                    SkillResolutionWarning(
                                        url=skill.url,
                                        reason="Has the same name as a predefined"
                                        " skill; predefined takes precedence",
                                    )
                                )
                                continue
                            merged_skills.append(skill.metadata)
                            merged_contents[skill.metadata.name] = skill.content
                except Exception as exc:
                    catastrophic_reason = (
                        "Failed to resolve DIAL prompt skills; "
                        f"falling back to predefined-only: {exc}"
                    )

            # `catastrophic_reason` and `warnings` are mutually exclusive: the
            # resolver either returns (warnings only) or raises (catastrophic only).
            if catastrophic_reason is not None:
                self._render_catastrophic_stage(catastrophic_reason)
            elif warnings:
                self._render_warnings_stage(warnings)

            self._all_contents = merged_contents
            self._xml_cache = generate_skills_xml(merged_skills)
            self._resolved = True

    def _render_catastrophic_stage(self, reason: str) -> None:
        stage = self._stage_provider.get()
        stage.open()
        stage.append_name("Skill loading warnings")
        stage.append_content(
            "#### DIAL prompt skills could not be loaded;"
            " falling back to predefined-only:\n"
            f"- {reason}"
        )
        stage.close(Status.COMPLETED)

    def _render_warnings_stage(self, warnings: list[SkillResolutionWarning]) -> None:
        stage = self._stage_provider.get()
        stage.open()
        stage.append_name("Skill loading warnings")
        lines = ["#### Some DIAL prompt skills could not be loaded:"]
        for w in warnings:
            lines.append(f"- **{w.url}**: {w.reason}")
        stage.append_content("\n".join(lines))
        stage.close(Status.COMPLETED)

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
