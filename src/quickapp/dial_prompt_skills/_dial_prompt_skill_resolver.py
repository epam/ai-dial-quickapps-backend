from __future__ import annotations

import asyncio

from aidial_client import AsyncDial
from injector import inject

from quickapp.config.skill import DialPromptSkillConfig
from quickapp.skills._exceptions import SkillResolutionWarning, SkillValidationError
from quickapp.skills._frontmatter import parse_frontmatter
from quickapp.skills.agent_skills_provider import SkillMetadata


@inject
class DialPromptSkillResolver:
    """Request-scoped resolver that fetches DIAL prompts and validates them as skills."""

    def __init__(self, dial_client: AsyncDial) -> None:
        self._dial_client = dial_client

    async def resolve(
        self,
        skill_configs: list[DialPromptSkillConfig],
    ) -> tuple[list[tuple[SkillMetadata, str]], list[SkillResolutionWarning]]:
        """Resolve skill configs into validated ``(SkillMetadata, content)`` pairs.

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
        resolved: list[tuple[SkillMetadata, str]] = []
        warnings: list[SkillResolutionWarning] = []
        seen_names: set[str] = set()

        for i, result in enumerate(results):
            url = unique_configs[i].url
            if isinstance(result, BaseException):
                warnings.append(SkillResolutionWarning(url=url, reason=str(result)))
                continue

            metadata, content = result
            if metadata.name in seen_names:
                warnings.append(
                    SkillResolutionWarning(
                        url=url,
                        reason=f"Duplicate skill name '{metadata.name}';"
                        " keeping first occurrence",
                    )
                )
                continue

            seen_names.add(metadata.name)
            resolved.append((metadata, content))

        return resolved, warnings

    async def _fetch_one(
        self,
        config: DialPromptSkillConfig,
    ) -> tuple[SkillMetadata, str]:
        """Fetch a single DIAL prompt and validate it as a skill."""
        prompt = await self._dial_client.prompts.get(config.url)

        if prompt.content is None or not prompt.content.strip():
            raise SkillValidationError(config.url, "DIAL prompt has no content")

        metadata = parse_frontmatter(prompt.content, config.url)
        return (metadata, prompt.content)
