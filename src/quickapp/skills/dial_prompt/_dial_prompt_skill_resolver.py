import asyncio

from aidial_client import AsyncDial
from injector import inject

from quickapp.common.exceptions import SkillInitializationException
from quickapp.config.skill import DialPromptSkillConfig
from quickapp.skills.exceptions import SkillValidationError
from quickapp.skills.frontmatter import parse_frontmatter
from quickapp.skills.skill_metadata import SkillMetadata
from quickapp.skills.skill_resolver import SkillResolution
from quickapp.skills.skills_provider import ResolvedSkill


async def fetch_and_validate_dial_prompt_skill(
    client: AsyncDial, url: str
) -> tuple[SkillMetadata, str]:
    """Fetch a DIAL prompt by URL and validate it as a skill.

    Returns ``(metadata, content)``. Raises ``DialException`` if the fetch
    fails and ``SkillValidationError`` if the prompt is empty or its
    frontmatter is invalid.
    """
    prompt = await client.prompts.get(url)
    if prompt.content is None or not prompt.content.strip():
        raise SkillValidationError(url, "DIAL prompt has no content")
    return parse_frontmatter(prompt.content, url), prompt.content


@inject
class DialPromptSkillResolver:
    """Request-scoped resolver that fetches DIAL prompts and validates them as skills."""

    def __init__(self, dial_client: AsyncDial) -> None:
        self._dial_client = dial_client

    async def resolve(
        self,
        skill_configs: list[DialPromptSkillConfig],
    ) -> SkillResolution:
        """Resolve skill configs into validated ``ResolvedSkill`` entries.

        - Deduplicates by URL before fetching.
        - Fetches in parallel with ``asyncio.gather(return_exceptions=True)``.
        - Deduplicates by skill name after fetching (first configured wins).
        - Per-URL failures become ``SkillInitializationException`` entries in
          the ``exceptions`` list and ride the unified initialization-issues flow.
        """
        seen_urls: set[str] = set()
        unique_configs: list[DialPromptSkillConfig] = []
        for cfg in skill_configs:
            if cfg.url not in seen_urls:
                seen_urls.add(cfg.url)
                unique_configs.append(cfg)

        if not unique_configs:
            return SkillResolution(resolved=[], exceptions=[])

        results = await asyncio.gather(
            *(self._fetch_one(cfg) for cfg in unique_configs),
            return_exceptions=True,
        )

        resolved: list[ResolvedSkill] = []
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

        return SkillResolution(resolved=resolved, exceptions=exceptions)

    async def _fetch_one(
        self,
        config: DialPromptSkillConfig,
    ) -> ResolvedSkill:
        metadata, content = await fetch_and_validate_dial_prompt_skill(
            self._dial_client, config.url
        )
        return ResolvedSkill(
            url=config.url,
            metadata=metadata,
            content=content,
        )
