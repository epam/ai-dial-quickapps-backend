import asyncio
import logging

from injector import inject
from pydantic import BaseModel, ConfigDict, Field

from quickapp.common.exceptions import SkillInitializationException
from quickapp.config.skill import DialSkillConfig
from quickapp.dial_skills._dial_skills_client import SkillInventory, _DialSkillsClient
from quickapp.dial_skills._exceptions import describe_exception
from quickapp.skills import SkillMetadata, parse_frontmatter

logger = logging.getLogger(__name__)


class ResolvedDialSkill(BaseModel):
    """A successfully fetched DIAL skill resource, including its source URL."""

    model_config = ConfigDict(frozen=True)

    url: str
    metadata: SkillMetadata
    content: str
    files: tuple[str, ...] = ()
    warnings: list[str] = Field(default_factory=list)


class DialSkillResolverOutput(BaseModel):
    """Return shape of ``DialSkillResolver.resolve``."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    resolved: list[ResolvedDialSkill]
    exceptions: list[SkillInitializationException]


def _build_skill_files_block(inventory: SkillInventory, max_files: int) -> str:
    """Render the ``<skill_files>`` inventory appended to a skill's manifest.

    Paths are emitted verbatim — deliberately not XML-escaped. Escaping would
    advertise `references/user's-guide.md` as `user&apos;s-guide.md`, a name no
    lookup resolves.
    """
    if not inventory.files:
        return ""
    block = "\n".join(("<skill_files>", *inventory.files, "</skill_files>"))
    if inventory.truncated:
        block += f"\nNote: file listing truncated at {max_files} entries."
    return block


@inject
class DialSkillResolver:
    """Request-scoped resolver that fetches DIAL skill resources and validates them."""

    def __init__(self, client: _DialSkillsClient) -> None:
        self._client = client

    async def resolve(
        self,
        skill_configs: list[DialSkillConfig],
    ) -> DialSkillResolverOutput:
        """Resolve skill configs into validated ``ResolvedDialSkill`` entries.

        Mirrors ``DialPromptSkillResolver.resolve``: dedup by URL, fetch in
        parallel, dedup by name (first configured wins), and turn both per-URL
        failures and non-fatal warnings into ``SkillInitializationException``
        entries distinguished by ``severity``.
        """
        seen_urls: set[str] = set()
        unique_configs: list[DialSkillConfig] = []
        for cfg in skill_configs:
            if cfg.url not in seen_urls:
                seen_urls.add(cfg.url)
                unique_configs.append(cfg)

        if not unique_configs:
            return DialSkillResolverOutput(resolved=[], exceptions=[])

        results = await asyncio.gather(*(self._fetch_labeled(cfg) for cfg in unique_configs))

        resolved: list[ResolvedDialSkill] = []
        exceptions: list[SkillInitializationException] = []
        seen_names: set[str] = set()

        for url, result in results:
            if isinstance(result, BaseException):
                exceptions.append(
                    SkillInitializationException(url=url, reason=describe_exception(result))
                )
                continue

            for warning in result.warnings:
                exceptions.append(
                    SkillInitializationException(url=url, reason=warning, severity="warning")
                )

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

        return DialSkillResolverOutput(resolved=resolved, exceptions=exceptions)

    async def _fetch_labeled(
        self, config: DialSkillConfig
    ) -> tuple[str, ResolvedDialSkill | BaseException]:
        """Fetch one skill, pairing the result with its own URL.

        Pairing here (rather than correlating results back to
        ``unique_configs`` by position) keeps the association obvious at the
        call site instead of resting on ``asyncio.gather`` preserving order.
        """
        try:
            return config.url, await self._fetch_one(config)
        except BaseException as exc:
            return config.url, exc

    async def _fetch_one(self, config: DialSkillConfig) -> ResolvedDialSkill:
        manifest = await self._client.read_manifest(config.url)
        parsed = parse_frontmatter(manifest, config.url)

        inventory, warnings = await self._list_files(config.url)
        block = _build_skill_files_block(inventory, self._client.max_files)
        content = f"{manifest.rstrip()}\n\n{block}\n" if block else manifest

        return ResolvedDialSkill(
            url=config.url,
            metadata=parsed.metadata,
            content=content,
            files=inventory.files,
            warnings=[*parsed.warnings, *warnings],
        )

    async def _list_files(self, url: str) -> tuple[SkillInventory, list[str]]:
        """List a skill's files, degrading to "no bundled files" on failure.

        A skill whose manifest reads fine is still useful without its inventory,
        so a listing failure downgrades the skill rather than dropping it.
        """
        try:
            return await self._client.list_text_files(url), []
        except Exception as exc:
            logger.warning("Failed to list files of a DIAL skill: %s", describe_exception(exc))
            return SkillInventory(), [
                f"Could not list bundled files: {describe_exception(exc)};"
                " the skill is available without them"
            ]
