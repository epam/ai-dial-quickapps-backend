from __future__ import annotations

import asyncio

from aidial_client import AsyncDial
from injector import inject
from pydantic import BaseModel, ConfigDict

from quickapp.config.skill import DialPromptSkillConfig
from quickapp.skills._exceptions import SkillResolutionWarning, SkillValidationError
from quickapp.skills._frontmatter import parse_frontmatter
from quickapp.skills.agent_skills_provider import SkillMetadata


class ResolvedDialPromptSkill(BaseModel):
    """A successfully fetched DIAL prompt skill, including its source URL."""

    model_config = ConfigDict(frozen=True)

    url: str
    metadata: SkillMetadata
    content: str


@inject
class DialPromptSkillResolver:
    """Request-scoped resolver that fetches DIAL prompts and validates them as skills."""

    def __init__(self, dial_client: AsyncDial) -> None:
        self._dial_client = dial_client

    async def resolve(
        self,
        skill_configs: list[DialPromptSkillConfig],
    ) -> tuple[list[ResolvedDialPromptSkill], list[SkillResolutionWarning]]:
        """Resolve skill configs into validated ``ResolvedDialPromptSkill`` entries.

        Returns a tuple of (resolved_skills, warnings).

        - Deduplicates by URL before fetching.
        - Fetches in parallel with ``asyncio.gather(return_exceptions=True)``.
        - Deduplicates by skill name after fetching (first configured wins).
        """
        # Deduplicate by URL (preserve first occurrence)
        seen_urls: set[str] = set()
        unique_configs: list[DialPromptSkillConfig] = []
        for cfg in skill_configs:
            if cfg.url not in seen_urls:
                seen_urls.add(cfg.url)
                unique_configs.append(cfg)

        if not unique_configs:
            return [], []

        # Fetch in parallel
        results = await asyncio.gather(
            *(self._fetch_one(cfg) for cfg in unique_configs),
            return_exceptions=True,
        )

        # Filter exceptions, deduplicate by name, collect warnings
        resolved: list[ResolvedDialPromptSkill] = []
        warnings: list[SkillResolutionWarning] = []
        seen_names: set[str] = set()

        for i, result in enumerate(results):
            url = unique_configs[i].url
            if isinstance(result, BaseException):
                warnings.append(SkillResolutionWarning(url=url, reason=str(result)))
                continue

            if result.metadata.name in seen_names:
                warnings.append(
                    SkillResolutionWarning(
                        url=url,
                        reason=f"Duplicate skill name '{result.metadata.name}';"
                        " keeping first occurrence",
                    )
                )
                continue

            seen_names.add(result.metadata.name)
            resolved.append(result)

        return resolved, warnings

    async def _fetch_one(
        self,
        config: DialPromptSkillConfig,
    ) -> ResolvedDialPromptSkill:
        """Fetch a single DIAL prompt and validate it as a skill."""
        prompt = await self._dial_client.prompts.get(config.url)

        if prompt.content is None or not prompt.content.strip():
            raise SkillValidationError(config.url, "DIAL prompt has no content")

        metadata = parse_frontmatter(prompt.content, config.url)
        return ResolvedDialPromptSkill(
            url=config.url,
            metadata=metadata,
            content=prompt.content,
        )
