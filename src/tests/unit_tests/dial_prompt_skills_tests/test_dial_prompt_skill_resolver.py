from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.config.skill import DialPromptSkillConfig
from quickapp.dial_prompt_skills._dial_prompt_skill_resolver import DialPromptSkillResolver


def _make_prompt(content: str | None = None, name: str = "p", folder_id: str = "f") -> MagicMock:
    prompt = MagicMock()
    prompt.id = f"{folder_id}/{name}"
    prompt.name = name
    prompt.folder_id = folder_id
    prompt.content = content
    return prompt


def _make_config(url: str = "prompts/bucket/my-skill") -> DialPromptSkillConfig:
    return DialPromptSkillConfig(url=url)


def _make_resolver(
    prompts_get_side_effect=None, prompts_get_return=None
) -> DialPromptSkillResolver:
    dial_client = MagicMock()
    dial_client.prompts = MagicMock()
    if prompts_get_side_effect is not None:
        dial_client.prompts.get = AsyncMock(side_effect=prompts_get_side_effect)
    elif prompts_get_return is not None:
        dial_client.prompts.get = AsyncMock(return_value=prompts_get_return)
    else:
        dial_client.prompts.get = AsyncMock(return_value=_make_prompt())
    return DialPromptSkillResolver(dial_client=dial_client)


VALID_SKILL_CONTENT = (
    "---\n"
    "name: my-skill\n"
    "description: A test skill from DIAL\n"
    "---\n"
    "# My Skill\n"
    "Full content here.\n"
)


class TestDialPromptSkillResolver:
    @pytest.mark.asyncio
    async def test_successful_single_fetch(self):
        prompt = _make_prompt(content=VALID_SKILL_CONTENT)
        resolver = _make_resolver(prompts_get_return=prompt)

        configs = [_make_config("prompts/bucket/my-skill")]
        output = await resolver.resolve(configs)

        assert len(output.resolved) == 1
        assert len(output.exceptions) == 0
        skill = output.resolved[0]
        assert skill.url == "prompts/bucket/my-skill"
        assert skill.metadata.name == "my-skill"
        assert skill.metadata.description == "A test skill from DIAL"
        assert "Full content here." in skill.content

    @pytest.mark.asyncio
    async def test_empty_content_skipped(self):
        prompt = _make_prompt(content="")
        resolver = _make_resolver(prompts_get_return=prompt)

        output = await resolver.resolve([_make_config()])

        assert len(output.resolved) == 0
        assert len(output.exceptions) == 1
        assert "no content" in output.exceptions[0].reason.lower()

    @pytest.mark.asyncio
    async def test_none_content_skipped(self):
        prompt = _make_prompt(content=None)
        resolver = _make_resolver(prompts_get_return=prompt)

        output = await resolver.resolve([_make_config()])

        assert len(output.resolved) == 0
        assert len(output.exceptions) == 1
        assert "no content" in output.exceptions[0].reason.lower()

    @pytest.mark.asyncio
    async def test_invalid_frontmatter_skipped(self):
        prompt = _make_prompt(content="No frontmatter here, just text.")
        resolver = _make_resolver(prompts_get_return=prompt)

        output = await resolver.resolve([_make_config()])

        assert len(output.resolved) == 0
        assert len(output.exceptions) == 1
        assert "frontmatter" in output.exceptions[0].reason.lower()

    @pytest.mark.asyncio
    async def test_url_deduplication(self):
        prompt = _make_prompt(content=VALID_SKILL_CONTENT)
        dial_client = MagicMock()
        dial_client.prompts = MagicMock()
        dial_client.prompts.get = AsyncMock(return_value=prompt)
        resolver = DialPromptSkillResolver(dial_client=dial_client)

        same_url = "prompts/bucket/my-skill"
        configs = [_make_config(same_url), _make_config(same_url)]
        output = await resolver.resolve(configs)

        assert len(output.resolved) == 1
        assert len(output.exceptions) == 0
        dial_client.prompts.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_name_deduplication(self):
        """Two different URLs resolve to the same skill name — first wins."""
        prompt1 = _make_prompt(content=VALID_SKILL_CONTENT)
        prompt2 = _make_prompt(content=VALID_SKILL_CONTENT)

        dial_client = MagicMock()
        dial_client.prompts = MagicMock()
        dial_client.prompts.get = AsyncMock(side_effect=[prompt1, prompt2])
        resolver = DialPromptSkillResolver(dial_client=dial_client)

        configs = [
            _make_config("prompts/bucket/skill-a"),
            _make_config("prompts/bucket/skill-b"),
        ]
        output = await resolver.resolve(configs)

        assert len(output.resolved) == 1
        assert output.resolved[0].url == "prompts/bucket/skill-a"
        assert output.resolved[0].metadata.name == "my-skill"
        assert len(output.exceptions) == 1
        assert output.exceptions[0].url == "prompts/bucket/skill-b"
        assert "Duplicate" in output.exceptions[0].reason

    @pytest.mark.asyncio
    async def test_fetch_failure_does_not_block_others(self):
        valid_prompt = _make_prompt(content=VALID_SKILL_CONTENT)

        dial_client = MagicMock()
        dial_client.prompts = MagicMock()
        dial_client.prompts.get = AsyncMock(
            side_effect=[RuntimeError("Network error"), valid_prompt]
        )
        resolver = DialPromptSkillResolver(dial_client=dial_client)

        configs = [
            _make_config("prompts/bucket/broken"),
            _make_config("prompts/bucket/working"),
        ]
        output = await resolver.resolve(configs)

        assert len(output.resolved) == 1
        assert output.resolved[0].url == "prompts/bucket/working"
        assert output.resolved[0].metadata.name == "my-skill"
        assert len(output.exceptions) == 1
        assert output.exceptions[0].url == "prompts/bucket/broken"
        assert "Network error" in output.exceptions[0].reason

    @pytest.mark.asyncio
    async def test_empty_configs_returns_empty(self):
        resolver = _make_resolver()
        output = await resolver.resolve([])
        assert output.resolved == []
        assert output.exceptions == []

    @pytest.mark.asyncio
    async def test_long_name_resolves_with_warning(self):
        """A name >64 chars used to be a per-URL failure; now it resolves."""
        long_name = "a" * 65
        content = f"---\nname: {long_name}\ndescription: desc\n---\nBody\n"
        prompt = _make_prompt(content=content)
        resolver = _make_resolver(prompts_get_return=prompt)

        output = await resolver.resolve([_make_config()])

        assert len(output.resolved) == 1
        assert output.resolved[0].metadata.name == long_name
        assert output.exceptions == []

    @pytest.mark.asyncio
    async def test_bom_prefixed_content_resolves(self):
        """Content stored with a leading BOM (common after copy/paste) now parses."""
        content = "﻿" + VALID_SKILL_CONTENT
        prompt = _make_prompt(content=content)
        resolver = _make_resolver(prompts_get_return=prompt)

        output = await resolver.resolve([_make_config()])

        assert len(output.resolved) == 1
        assert output.resolved[0].metadata.name == "my-skill"
        assert output.exceptions == []

    @pytest.mark.asyncio
    async def test_closing_fence_at_eof_resolves(self):
        """Content with no trailing newline after the closing fence now parses."""
        content = "---\nname: my-skill\ndescription: desc\n---"
        prompt = _make_prompt(content=content)
        resolver = _make_resolver(prompts_get_return=prompt)

        output = await resolver.resolve([_make_config()])

        assert len(output.resolved) == 1
        assert output.resolved[0].metadata.name == "my-skill"
        assert output.exceptions == []
