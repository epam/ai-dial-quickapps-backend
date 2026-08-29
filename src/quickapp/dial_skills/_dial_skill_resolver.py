import asyncio
import logging
from typing import NamedTuple

from injector import inject

from quickapp.common.exceptions import SkillInitializationException
from quickapp.config.skill import DialSkillConfig
from quickapp.dial_skills._dial_skill import _DialSkill
from quickapp.dial_skills._dial_skills_client import DialSkillsClient
from quickapp.dial_skills._settings import DialSkillsSettings
from quickapp.skills._frontmatter import parse_frontmatter

logger = logging.getLogger(__name__)

_URL_PREFIX = "skills/"
_FILES_SEGMENT = "files"
_EXPECTED_SHAPE = "expected 'skills/<bucket>/<path>' addressing the skill itself"


class DialSkillResolverOutput(NamedTuple):
    """Return shape of ``DialSkillResolver.resolve``."""

    resolved: list[_DialSkill]
    exceptions: list[SkillInitializationException]


@inject
class DialSkillResolver:
    """Request-scoped resolver that fetches DIAL skill resources and validates them.

    Owns fetching and validation only. Precedence between skills — including
    between a ``dial-skill`` and a ``dial-prompt`` of the same name — belongs to
    ``SkillsRegistry``, the one component that sees every source.
    """

    def __init__(
        self,
        client: DialSkillsClient,
        settings: DialSkillsSettings,
    ) -> None:
        self._client = client
        self._settings = settings

    async def resolve(
        self,
        skill_configs: list[tuple[int, DialSkillConfig]],
    ) -> DialSkillResolverOutput:
        """Resolve indexed ``dial-skill`` configs into validated skills.

        Order of operations, which is what makes the two failure modes interact
        predictably: dedup by URL, then validate URL shape, then apply the cap,
        then fetch in parallel. Dedup runs first so a URL pasted twice is
        diagnosed once instead of twice; validation precedes the cap so a
        malformed URL never consumes a cap slot. The cap therefore counts
        *unique, well-formed* URLs.
        """
        exceptions: list[SkillInitializationException] = []

        seen_urls: set[str] = set()
        candidates: list[tuple[int, str]] = []
        for index, cfg in skill_configs:
            if cfg.url in seen_urls:
                # Not a loss — the skill is still resolved from its first
                # occurrence — so this collapse is deliberately silent.
                continue
            seen_urls.add(cfg.url)

            if reason := invalid_skill_url_reason(cfg.url):
                exceptions.append(SkillInitializationException(url=cfg.url, reason=reason))
                continue
            candidates.append((index, cfg.url))

        cap = self._settings.max_configured_skills
        if len(candidates) > cap:
            for _, url in candidates[cap:]:
                exceptions.append(
                    SkillInitializationException(
                        url=url,
                        reason=(
                            f"Skipped: more than {cap} DIAL skills are configured"
                            " (DIAL_SKILLS_MAX_CONFIGURED_SKILLS)"
                        ),
                    )
                )
            candidates = candidates[:cap]

        if not candidates:
            return DialSkillResolverOutput(resolved=[], exceptions=exceptions)

        results = await asyncio.gather(
            *(self._fetch_one(index, url) for index, url in candidates),
            return_exceptions=True,
        )

        resolved: list[_DialSkill] = []
        for (_, url), result in zip(candidates, results, strict=True):
            if isinstance(result, BaseException):
                exceptions.append(SkillInitializationException(url=url, reason=str(result)))
                continue

            skill, warnings = result
            for warning in warnings:
                exceptions.append(
                    SkillInitializationException(url=url, reason=warning, severity="warning")
                )
            resolved.append(skill)

        return DialSkillResolverOutput(resolved=resolved, exceptions=exceptions)

    async def _fetch_one(
        self,
        config_index: int,
        url: str,
    ) -> tuple[_DialSkill, list[str]]:
        # `return_exceptions=True` here too, unlike a bare gather: a bare one
        # propagates the first failure without cancelling its sibling, so the
        # common 403/404 case left an inventory pagination running against a
        # request-scoped client the request had already moved past.
        manifest, inventory = await asyncio.gather(
            self._client.get_manifest(url),
            self._client.list_files(url),
            return_exceptions=True,
        )
        if isinstance(manifest, BaseException):
            raise manifest
        if isinstance(inventory, BaseException):
            raise inventory

        files, truncated = inventory
        parsed = parse_frontmatter(manifest, url)
        skill = _DialSkill(
            metadata=parsed.metadata,
            manifest=manifest,
            files=files,
            url=url,
            config_index=config_index,
            client=self._client,
            files_truncated=truncated,
        )
        return skill, parsed.warnings


def invalid_skill_url_reason(url: str) -> str | None:
    """Return why ``url`` is not a skill-resource URL, or ``None`` if it is.

    Checked here rather than in the config model: a ``ValidationError`` during
    config parsing is not a ``ConfigResolutionException``, so it escapes the
    branch that renders the initialization-issues stage and would fail the whole
    request over one malformed URL.
    """
    if not url.startswith(_URL_PREFIX):
        return f"Not a DIAL skill URL; {_EXPECTED_SHAPE}"
    if url.endswith("/"):
        return f"Trailing slash addresses a folder, not a skill; {_EXPECTED_SHAPE}"

    segments = url.split("/")
    if len(segments) < 3 or not all(segments):
        return f"Incomplete skill URL; {_EXPECTED_SHAPE}"
    if _FILES_SEGMENT in segments[2:]:
        return f"Addresses a file inside a skill rather than the skill itself; {_EXPECTED_SHAPE}"
    return None
