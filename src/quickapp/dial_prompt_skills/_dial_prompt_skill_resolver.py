from __future__ import annotations

import asyncio

from aidial_client import AsyncDial
from injector import inject
from pydantic import BaseModel, ConfigDict

from quickapp.common.exceptions import SkillInitializationException
from quickapp.config.skill import DialPromptSkillConfig
from quickapp.skills._exceptions import SkillValidationError
from quickapp.skills._frontmatter import parse_frontmatter
from quickapp.skills._skill_metadata import SkillMetadata


class ResolvedDialPromptSkill(BaseModel):
    """A successfully fetched DIAL prompt skill, including its source URL."""

    model_config = ConfigDict(frozen=True)

    url: str
    metadata: SkillMetadata
    content: str


class DialPromptSkillResolverOutput(BaseModel):
    """Return shape of ``DialPromptSkillResolver.resolve``."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    resolved: list[ResolvedDialPromptSkill]
    exceptions: list[SkillInitializationException]


async def fetch_and_validate_dial_prompt_skill(
    client: AsyncDial, url: str
) -> tuple[SkillMetadata, str]:
    """Fetch a DIAL prompt by URL and validate it as a skill.

    Raises ``DialException`` if the fetch fails and ``SkillValidationError``
    if the prompt is empty or its frontmatter is invalid.
    """
    prompt = await client.prompts.get(url)
    if prompt.content is None or not prompt.content.strip():
        raise SkillValidationError(url, "DIAL prompt has no content")
    metadata = parse_frontmatter(prompt.content, url)
    return metadata, prompt.content


@inject
class DialPromptSkillResolver:
    """Request-scoped resolver that fetches DIAL prompts and validates them as skills."""

    def __init__(self, dial_client: AsyncDial) -> None:
        self._dial_client = dial_client

    async def resolve(
        self,
        skill_configs: list[DialPromptSkillConfig],
    ) -> DialPromptSkillResolverOutput:
        """Resolve skill configs into validated ``ResolvedDialPromptSkill`` entries.

        - Deduplicates by URL before fetching.
        - Fetches in parallel with ``asyncio.gather(return_exceptions=True)``.
        - Deduplicates by skill name after fetching (first configured wins).
        - Every per-URL failure becomes a ``SkillInitializationException`` in
          the ``exceptions`` list — per the unified initialization-issues flow.
        """
        seen_urls: set[str] = set()
        unique_configs: list[DialPromptSkillConfig] = []
        for cfg in skill_configs:
            if cfg.url not in seen_urls:
                seen_urls.add(cfg.url)
                unique_configs.append(cfg)

        if not unique_configs:
            return DialPromptSkillResolverOutput(resolved=[], exceptions=[])

        results = await asyncio.gather(
            *(self._fetch_one(cfg) for cfg in unique_configs),
            return_exceptions=True,
        )

        resolved: list[ResolvedDialPromptSkill] = []
        exceptions: list[SkillInitializationException] = []
        seen_names: set[str] = set()

        for i, result in enumerate(results):
            url = unique_configs[i].url
            if isinstance(result, BaseException):
                exceptions.append(SkillInitializationException(url=url, reason=str(result)))
                continue

            if result.metadata.name in seen_names:
                exceptions.append(
                    SkillInitializationException(
                        url=url,
                        reason=(
                            f"Duplicate skill name '{result.metadata.name}';"
                            " keeping first occurrence"
                        ),
                    )
                )
                continue

            seen_names.add(result.metadata.name)
            resolved.append(result)

        return DialPromptSkillResolverOutput(resolved=resolved, exceptions=exceptions)

    async def _fetch_one(
        self,
        config: DialPromptSkillConfig,
    ) -> ResolvedDialPromptSkill:
        metadata, content = await fetch_and_validate_dial_prompt_skill(
            self._dial_client, config.url
        )
        return ResolvedDialPromptSkill(url=config.url, metadata=metadata, content=content)
