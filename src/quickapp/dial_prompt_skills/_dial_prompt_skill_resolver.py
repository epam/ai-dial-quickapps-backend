from __future__ import annotations

import asyncio
import logging

from aidial_client import AsyncDial
from injector import inject

from quickapp.config.skill import DialPromptSkillConfig
from quickapp.skills._frontmatter import parse_frontmatter
from quickapp.skills.agent_skills_provider import SkillMetadata

logger = logging.getLogger(__name__)


@inject
class DialPromptSkillResolver:
    """Request-scoped resolver that fetches DIAL prompts and validates them as skills."""

    def __init__(self, dial_client: AsyncDial) -> None:
        self._dial_client = dial_client

    async def resolve(
        self,
        skill_configs: list[DialPromptSkillConfig],
    ) -> list[tuple[SkillMetadata, str]]:
        """Resolve skill configs into validated ``(SkillMetadata, content)`` pairs.

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
            return []

        # Fetch in parallel
        results = await asyncio.gather(
            *(self._fetch_one(cfg) for cfg in unique_configs),
            return_exceptions=True,
        )

        # Filter exceptions and None results, deduplicate by name
        resolved: list[tuple[SkillMetadata, str]] = []
        seen_names: set[str] = set()

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.warning(
                    "Failed to fetch DIAL prompt skill at '%s': %s",
                    unique_configs[i].url,
                    result,
                )
                continue
            if result is None:
                continue

            metadata, content = result
            if metadata.name in seen_names:
                logger.warning(
                    "Duplicate skill name '%s' from DIAL prompt at '%s'; "
                    "keeping first occurrence.",
                    metadata.name,
                    unique_configs[i].url,
                )
                continue

            seen_names.add(metadata.name)
            resolved.append((metadata, content))

        return resolved

    async def _fetch_one(
        self,
        config: DialPromptSkillConfig,
    ) -> tuple[SkillMetadata, str] | None:
        """Fetch a single DIAL prompt and validate it as a skill."""
        prompt = await self._dial_client.prompts.get(config.url)

        if prompt.content is None or not prompt.content.strip():
            logger.warning(
                "DIAL prompt at '%s' has no content. Skipping as skill.",
                config.url,
            )
            return None

        metadata = parse_frontmatter(prompt.content, config.url)
        if metadata is None:
            return None

        return (metadata, prompt.content)
