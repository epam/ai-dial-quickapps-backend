from unittest.mock import AsyncMock, MagicMock

import pytest

# `quickapp.common.*` must be imported before `quickapp.config.skill`: the two
# packages form a pre-existing import cycle (common/__init__ -> staged_base_tool
# -> config.application -> config.skill), which only bites when config.skill is
# the first of them to load. Keep this import above the config one.
from quickapp.common.exceptions import SkillInitializationException
from quickapp.config.skill import DialSkillConfig
from quickapp.dial_skills._dial_skill_resolver import DialSkillResolver
from quickapp.dial_skills._dial_skills_client import SkillInventory
from quickapp.dial_skills._exceptions import DialSkillFileReadError

MANIFEST = """---
name: refund-policy
description: How to handle refunds.
---

# Refund Policy
"""


def _make_resolver(
    *,
    manifest: str = MANIFEST,
    inventory: SkillInventory | None = None,
    max_files: int = 200,
) -> tuple[DialSkillResolver, MagicMock]:
    client = MagicMock()
    client.max_files = max_files
    client.read_manifest = AsyncMock(return_value=manifest)
    client.list_text_files = AsyncMock(return_value=inventory or SkillInventory())
    return DialSkillResolver(client), client


def _config(url: str) -> DialSkillConfig:
    return DialSkillConfig(url=url)


class TestResolve:

    @pytest.mark.asyncio
    async def test_resolves_manifest_and_inventory(self):
        inventory = SkillInventory(files=("references/eu.md", "references/us.md"))
        resolver, _ = _make_resolver(inventory=inventory)

        output = await resolver.resolve([_config("skills/b/refund-policy")])

        assert not output.exceptions
        skill = output.resolved[0]
        assert skill.metadata.name == "refund-policy"
        assert skill.files == ("references/eu.md", "references/us.md")
        assert "<skill_files>\nreferences/eu.md\nreferences/us.md\n</skill_files>" in skill.content
        assert skill.content.startswith("---")

    @pytest.mark.asyncio
    async def test_no_inventory_block_when_skill_has_no_files(self):
        resolver, _ = _make_resolver()

        skill = (await resolver.resolve([_config("skills/b/plain")])).resolved[0]

        assert "<skill_files>" not in skill.content
        assert skill.content == MANIFEST

    @pytest.mark.asyncio
    async def test_truncated_inventory_is_flagged_to_the_model(self):
        inventory = SkillInventory(files=("a.md",), truncated=True)
        resolver, _ = _make_resolver(inventory=inventory, max_files=1)

        skill = (await resolver.resolve([_config("skills/b/big")])).resolved[0]

        assert "truncated at 1 entries" in skill.content

    @pytest.mark.asyncio
    async def test_paths_are_not_xml_escaped(self):
        inventory = SkillInventory(files=("references/user's-guide.md",))
        resolver, _ = _make_resolver(inventory=inventory)

        skill = (await resolver.resolve([_config("skills/b/x")])).resolved[0]

        # An escaped path would advertise a name no lookup resolves.
        assert "references/user's-guide.md" in skill.content
        assert "&apos;" not in skill.content

    @pytest.mark.asyncio
    async def test_deduplicates_by_url_before_fetching(self):
        resolver, client = _make_resolver()

        output = await resolver.resolve([_config("skills/b/s"), _config("skills/b/s")])

        assert len(output.resolved) == 1
        assert client.read_manifest.await_count == 1

    @pytest.mark.asyncio
    async def test_duplicate_name_keeps_first_and_reports(self):
        resolver, _ = _make_resolver()

        output = await resolver.resolve([_config("skills/b/one"), _config("skills/b/two")])

        assert len(output.resolved) == 1
        assert output.resolved[0].url == "skills/b/one"
        assert "Duplicate skill name 'refund-policy'" in output.exceptions[0].reason

    @pytest.mark.asyncio
    async def test_manifest_failure_drops_the_skill(self):
        resolver, client = _make_resolver()
        client.read_manifest = AsyncMock(
            side_effect=DialSkillFileReadError("SKILL.md", "403 Forbidden")
        )

        output = await resolver.resolve([_config("skills/b/denied")])

        assert output.resolved == []
        assert isinstance(output.exceptions[0], SkillInitializationException)
        assert "403 Forbidden" in output.exceptions[0].reason
        assert output.exceptions[0].url == "skills/b/denied"

    @pytest.mark.asyncio
    async def test_invalid_frontmatter_drops_the_skill(self):
        resolver, _ = _make_resolver(manifest="no frontmatter here")

        output = await resolver.resolve([_config("skills/b/broken")])

        assert output.resolved == []
        assert "No YAML frontmatter found" in output.exceptions[0].reason

    @pytest.mark.asyncio
    async def test_listing_failure_keeps_the_skill_with_a_warning(self):
        resolver, client = _make_resolver()
        client.list_text_files = AsyncMock(side_effect=TimeoutError())

        output = await resolver.resolve([_config("skills/b/s")])

        # The manifest read fine; the skill is still useful without its files.
        assert output.resolved[0].files == ()
        warning = output.exceptions[0]
        assert warning.severity == "warning"
        assert "Could not list bundled files: TimeoutError" in warning.reason

    @pytest.mark.asyncio
    async def test_parser_warnings_ride_as_warnings(self):
        manifest = "---\nname: Refund_Policy\ndescription: d\n---\nbody"
        resolver, _ = _make_resolver(manifest=manifest)

        output = await resolver.resolve([_config("skills/b/s")])

        assert output.resolved
        assert all(exc.severity == "warning" for exc in output.exceptions)

    @pytest.mark.asyncio
    async def test_empty_config_list_does_no_io(self):
        resolver, client = _make_resolver()

        output = await resolver.resolve([])

        assert output.resolved == []
        assert client.read_manifest.await_count == 0
