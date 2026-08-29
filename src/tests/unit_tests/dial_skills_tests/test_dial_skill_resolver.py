from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.exceptions import SkillInitializationException
from quickapp.config.skill import DialSkillConfig
from quickapp.dial_skills._dial_skill_resolver import DialSkillResolver
from quickapp.dial_skills._dial_skills_client import DialSkillsClient
from quickapp.dial_skills._exceptions import SkillAccessDenied
from quickapp.dial_skills._settings import DialSkillsSettings
from quickapp.skills._skill import SkillFileEntry

VALID_MANIFEST = "---\nname: refunds\ndescription: Refund policy\n---\n# Refunds\n"


def _indexed(*urls: str) -> list[tuple[int, DialSkillConfig]]:
    return [(i, DialSkillConfig(url=url)) for i, url in enumerate(urls)]


def _make_resolver(
    manifest: str | AsyncMock = VALID_MANIFEST,
    files: list[str] | None = None,
    truncated: bool = False,
    max_configured_skills: int = 20,
) -> tuple[DialSkillResolver, MagicMock]:
    client = MagicMock(spec=DialSkillsClient)
    client.get_manifest = (
        manifest if isinstance(manifest, AsyncMock) else AsyncMock(return_value=manifest)
    )
    client.list_files = AsyncMock(
        return_value=([SkillFileEntry(path=p) for p in files or []], truncated)
    )
    resolver = DialSkillResolver(
        client=client,
        settings=DialSkillsSettings(max_configured_skills=max_configured_skills),
    )
    return resolver, client


class TestResolution:
    @pytest.mark.asyncio
    async def test_resolves_manifest_and_inventory(self):
        resolver, _ = _make_resolver(files=["references/matrix.md"])

        output = await resolver.resolve(_indexed("skills/b/support/refunds"))

        assert output.exceptions == []
        skill = output.resolved[0]
        assert skill.metadata.name == "refunds"
        assert skill.read_manifest() == VALID_MANIFEST
        assert [e.path for e in skill.list_files()] == ["references/matrix.md"]
        assert skill.config_index == 0
        assert skill.url == "skills/b/support/refunds"

    @pytest.mark.asyncio
    async def test_truncated_inventory_is_carried_onto_the_skill(self):
        resolver, _ = _make_resolver(files=["a.md"], truncated=True)

        output = await resolver.resolve(_indexed("skills/b/s"))

        assert output.resolved[0].inventory_truncated is True

    @pytest.mark.asyncio
    async def test_frontmatter_warnings_become_warning_diagnostics(self):
        long_name = "a" * 65
        resolver, _ = _make_resolver(
            manifest=f"---\nname: {long_name}\ndescription: d\n---\nBody\n"
        )

        output = await resolver.resolve(_indexed("skills/b/long"))

        assert len(output.resolved) == 1
        warning = output.exceptions[0]
        assert isinstance(warning, SkillInitializationException)
        assert warning.severity == "warning"
        assert "exceeds 64 characters" in warning.reason

    @pytest.mark.asyncio
    async def test_invalid_frontmatter_skips_the_skill(self):
        resolver, _ = _make_resolver(manifest="no frontmatter here")

        output = await resolver.resolve(_indexed("skills/b/broken"))

        assert output.resolved == []
        assert "frontmatter" in output.exceptions[0].reason.lower()

    @pytest.mark.asyncio
    async def test_one_failure_does_not_block_the_others(self):
        resolver, client = _make_resolver()
        client.get_manifest = AsyncMock(side_effect=[SkillAccessDenied("denied"), VALID_MANIFEST])

        output = await resolver.resolve(_indexed("skills/b/denied", "skills/b/ok"))

        assert [s.url for s in output.resolved] == ["skills/b/ok"]
        assert [e.url for e in output.exceptions] == ["skills/b/denied"]

    @pytest.mark.asyncio
    async def test_empty_configs_short_circuit(self):
        resolver, client = _make_resolver()

        output = await resolver.resolve([])

        assert output.resolved == []
        assert output.exceptions == []
        client.get_manifest.assert_not_awaited()


class TestUrlValidation:
    """Rejected at resolve time, not config-parse time: a ValidationError
    would escape the branch that renders the initialization-issues stage."""

    @pytest.mark.parametrize(
        "url",
        [
            "prompts/bucket/my-skill",
            "bucket/my-skill",
            "skills/bucket/my-skill/",
            "skills/bucket",
            "skills//my-skill",
            "skills/bucket/my-skill/files/SKILL.md",
        ],
    )
    @pytest.mark.asyncio
    async def test_malformed_urls_are_diagnosed_not_fetched(self, url: str):
        resolver, client = _make_resolver()

        output = await resolver.resolve(_indexed(url))

        assert output.resolved == []
        assert [e.url for e in output.exceptions] == [url]
        client.get_manifest.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_malformed_url_does_not_consume_a_cap_slot(self):
        resolver, client = _make_resolver(max_configured_skills=1)

        output = await resolver.resolve(_indexed("not-a-skill-url", "skills/b/good"))

        assert [s.url for s in output.resolved] == ["skills/b/good"]
        assert [e.url for e in output.exceptions] == ["not-a-skill-url"]


class TestDedupAndCap:
    @pytest.mark.asyncio
    async def test_a_repeated_url_is_fetched_once_and_reported_never(self):
        resolver, client = _make_resolver()

        output = await resolver.resolve(_indexed("skills/b/s", "skills/b/s"))

        assert len(output.resolved) == 1
        assert output.exceptions == []
        client.get_manifest.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_deduped_skill_keeps_the_first_occurrence_index(self):
        resolver, _ = _make_resolver()

        output = await resolver.resolve(_indexed("skills/b/other", "skills/b/s", "skills/b/s"))

        by_url = {s.url: s.config_index for s in output.resolved}
        assert by_url["skills/b/s"] == 1

    @pytest.mark.asyncio
    async def test_the_cap_counts_unique_urls_not_config_entries(self):
        resolver, _ = _make_resolver(max_configured_skills=2)

        output = await resolver.resolve(
            _indexed("skills/b/a", "skills/b/a", "skills/b/b", "skills/b/b")
        )

        assert len(output.resolved) == 2
        assert output.exceptions == []

    @pytest.mark.asyncio
    async def test_urls_beyond_the_cap_are_skipped_with_a_diagnostic(self):
        resolver, _ = _make_resolver(max_configured_skills=1)

        output = await resolver.resolve(_indexed("skills/b/kept", "skills/b/dropped"))

        assert [s.url for s in output.resolved] == ["skills/b/kept"]
        assert [e.url for e in output.exceptions] == ["skills/b/dropped"]
        assert "DIAL_SKILLS_MAX_CONFIGURED_SKILLS" in output.exceptions[0].reason
