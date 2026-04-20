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
        result, warnings = await resolver.resolve(configs)

        assert len(result) == 1
        assert len(warnings) == 0
        skill = result[0]
        assert skill.url == "prompts/bucket/my-skill"
        assert skill.metadata.name == "my-skill"
        assert skill.metadata.description == "A test skill from DIAL"
        assert "Full content here." in skill.content

    @pytest.mark.asyncio
    async def test_empty_content_skipped(self):
        prompt = _make_prompt(content="")
        resolver = _make_resolver(prompts_get_return=prompt)

        result, warnings = await resolver.resolve([_make_config()])

        assert len(result) == 0
        assert len(warnings) == 1
        assert "no content" in warnings[0].reason.lower()

    @pytest.mark.asyncio
    async def test_none_content_skipped(self):
        prompt = _make_prompt(content=None)
        resolver = _make_resolver(prompts_get_return=prompt)

        result, warnings = await resolver.resolve([_make_config()])

        assert len(result) == 0
        assert len(warnings) == 1
        assert "no content" in warnings[0].reason.lower()

    @pytest.mark.asyncio
    async def test_invalid_frontmatter_skipped(self):
        prompt = _make_prompt(content="No frontmatter here, just text.")
        resolver = _make_resolver(prompts_get_return=prompt)

        result, warnings = await resolver.resolve([_make_config()])

        assert len(result) == 0
        assert len(warnings) == 1
        assert "frontmatter" in warnings[0].reason.lower()

    @pytest.mark.asyncio
    async def test_url_deduplication(self):
        prompt = _make_prompt(content=VALID_SKILL_CONTENT)
        dial_client = MagicMock()
        dial_client.prompts = MagicMock()
        dial_client.prompts.get = AsyncMock(return_value=prompt)
        resolver = DialPromptSkillResolver(dial_client=dial_client)

        same_url = "prompts/bucket/my-skill"
        configs = [_make_config(same_url), _make_config(same_url)]
        result, warnings = await resolver.resolve(configs)

        assert len(result) == 1
        assert len(warnings) == 0
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
        result, warnings = await resolver.resolve(configs)

        assert len(result) == 1
        assert result[0].url == "prompts/bucket/skill-a"
        assert result[0].metadata.name == "my-skill"
        assert len(warnings) == 1
        assert warnings[0].url == "prompts/bucket/skill-b"
        assert "Duplicate" in warnings[0].reason

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
        result, warnings = await resolver.resolve(configs)

        assert len(result) == 1
        assert result[0].url == "prompts/bucket/working"
        assert result[0].metadata.name == "my-skill"
        assert len(warnings) == 1
        assert warnings[0].url == "prompts/bucket/broken"
        assert "Network error" in warnings[0].reason

    @pytest.mark.asyncio
    async def test_empty_configs_returns_empty(self):
        resolver = _make_resolver()
        result, warnings = await resolver.resolve([])
        assert result == []
        assert warnings == []
