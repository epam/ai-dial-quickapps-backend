import asyncio
from typing import NamedTuple

from aidial_client import AsyncDial
from injector import inject

from quickapp.common.exceptions import SkillInitializationException
from quickapp.config.skill import DialPromptSkillConfig
from quickapp.dial_prompt_skills._dial_prompt_skill import _DialPromptSkill
from quickapp.skills._exceptions import SkillValidationError
from quickapp.skills._frontmatter import parse_frontmatter
from quickapp.skills._skill_metadata import ParsedSkill


class DialPromptSkillResolverOutput(NamedTuple):
    """Return shape of ``DialPromptSkillResolver.resolve``."""

    resolved: list[_DialPromptSkill]
    exceptions: list[SkillInitializationException]


async def fetch_and_validate_dial_prompt_skill(
    client: AsyncDial, url: str
) -> tuple[ParsedSkill, str]:
    """Fetch a DIAL prompt by URL and validate it as a skill.

    Returns ``(parsed, content)``. Raises ``DialException`` if the fetch
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
        skill_configs: list[tuple[int, DialPromptSkillConfig]],
    ) -> DialPromptSkillResolverOutput:
        """Resolve indexed skill configs into validated ``_DialPromptSkill`` entries.

        - Deduplicates by URL before fetching, keeping the first occurrence's
          config index.
        - Fetches in parallel with ``asyncio.gather(return_exceptions=True)``.
        - Per-URL failures and non-fatal parser warnings both become
          ``SkillInitializationException`` entries in the ``exceptions`` list,
          distinguished by ``severity``. Both ride the unified
          initialization-issues flow.

        Name collisions are deliberately **not** resolved here. Precedence spans
        every source and this resolver can only see one of them, so dropping a
        name locally would discard a lower-indexed entry before
        ``SkillsRegistry`` — the only component that sees every source — could
        weigh it.
        """
        seen_urls: set[str] = set()
        unique_configs: list[tuple[int, DialPromptSkillConfig]] = []
        for index, cfg in skill_configs:
            if cfg.url not in seen_urls:
                seen_urls.add(cfg.url)
                unique_configs.append((index, cfg))

        if not unique_configs:
            return DialPromptSkillResolverOutput(resolved=[], exceptions=[])

        results = await asyncio.gather(
            *(self._fetch_one(index, cfg) for index, cfg in unique_configs),
            return_exceptions=True,
        )

        resolved: list[_DialPromptSkill] = []
        exceptions: list[SkillInitializationException] = []
        for i, result in enumerate(results):
            url = unique_configs[i][1].url
            if isinstance(result, BaseException):
                exceptions.append(SkillInitializationException(url=url, reason=str(result)))
                continue

            skill, warnings = result
            for warning in warnings:
                exceptions.append(
                    SkillInitializationException(url=url, reason=warning, severity="warning")
                )
            resolved.append(skill)

        return DialPromptSkillResolverOutput(resolved=resolved, exceptions=exceptions)

    async def _fetch_one(
        self,
        config_index: int,
        config: DialPromptSkillConfig,
    ) -> tuple[_DialPromptSkill, list[str]]:
        parsed, content = await fetch_and_validate_dial_prompt_skill(self._dial_client, config.url)
        skill = _DialPromptSkill(
            metadata=parsed.metadata,
            content=content,
            url=config.url,
            config_index=config_index,
        )
        return skill, parsed.warnings
