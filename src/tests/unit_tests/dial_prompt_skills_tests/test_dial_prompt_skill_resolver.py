from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.exceptions import SkillInitializationException
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


def _indexed(configs: list[DialPromptSkillConfig]) -> list[tuple[int, DialPromptSkillConfig]]:
    """Attach the config-list positions the initializer would assign."""
    return list(enumerate(configs))


def _issues(output) -> list[SkillInitializationException]:
    """The diagnostics a resolve reported."""
    return list(output.exceptions)


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
        output = await resolver.resolve(_indexed(configs))

        assert len(output.resolved) == 1
        assert len(_issues(output)) == 0
        skill = output.resolved[0]
        assert skill.url == "prompts/bucket/my-skill"
        assert skill.metadata.name == "my-skill"
        assert skill.metadata.description == "A test skill from DIAL"
        assert "Full content here." in skill.read_manifest()

    @pytest.mark.asyncio
    async def test_empty_content_skipped(self):
        prompt = _make_prompt(content="")
        resolver = _make_resolver(prompts_get_return=prompt)

        output = await resolver.resolve(_indexed([_make_config()]))

        assert len(output.resolved) == 0
        assert len(_issues(output)) == 1
        assert "no content" in _issues(output)[0].reason.lower()

    @pytest.mark.asyncio
    async def test_none_content_skipped(self):
        prompt = _make_prompt(content=None)
        resolver = _make_resolver(prompts_get_return=prompt)

        output = await resolver.resolve(_indexed([_make_config()]))

        assert len(output.resolved) == 0
        assert len(_issues(output)) == 1
        assert "no content" in _issues(output)[0].reason.lower()

    @pytest.mark.asyncio
    async def test_invalid_frontmatter_skipped(self):
        prompt = _make_prompt(content="No frontmatter here, just text.")
        resolver = _make_resolver(prompts_get_return=prompt)

        output = await resolver.resolve(_indexed([_make_config()]))

        assert len(output.resolved) == 0
        assert len(_issues(output)) == 1
        assert "frontmatter" in _issues(output)[0].reason.lower()

    @pytest.mark.asyncio
    async def test_url_deduplication(self):
        prompt = _make_prompt(content=VALID_SKILL_CONTENT)
        dial_client = MagicMock()
        dial_client.prompts = MagicMock()
        dial_client.prompts.get = AsyncMock(return_value=prompt)
        resolver = DialPromptSkillResolver(dial_client=dial_client)

        same_url = "prompts/bucket/my-skill"
        configs = [_make_config(same_url), _make_config(same_url)]
        output = await resolver.resolve(_indexed(configs))

        assert len(output.resolved) == 1
        assert len(_issues(output)) == 0
        dial_client.prompts.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_name_collisions_are_left_to_the_registry(self):
        """Two URLs resolving to one skill name both come back.

        Precedence spans every source and this resolver sees only one of them,
        so dropping a name here would discard an entry before ``SkillsRegistry``
        — the component that does see them all — could weigh it.
        """
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
        output = await resolver.resolve(_indexed(configs))

        assert [s.url for s in output.resolved] == [
            "prompts/bucket/skill-a",
            "prompts/bucket/skill-b",
        ]
        assert [s.config_index for s in output.resolved] == [0, 1]
        assert _issues(output) == []

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
        output = await resolver.resolve(_indexed(configs))

        assert len(output.resolved) == 1
        assert output.resolved[0].url == "prompts/bucket/working"
        assert output.resolved[0].metadata.name == "my-skill"
        assert len(_issues(output)) == 1
        assert _issues(output)[0].url == "prompts/bucket/broken"
        assert "Network error" in _issues(output)[0].reason

    @pytest.mark.asyncio
    async def test_empty_configs_returns_empty(self):
        resolver = _make_resolver()
        output = await resolver.resolve(_indexed([]))
        assert output.resolved == []
        assert _issues(output) == []

    @pytest.mark.asyncio
    async def test_long_name_resolves_with_warning(self):
        """A name >64 chars resolves and emits a SkillInitializationWarning."""
        long_name = "a" * 65
        content = f"---\nname: {long_name}\ndescription: desc\n---\nBody\n"
        prompt = _make_prompt(content=content)
        resolver = _make_resolver(prompts_get_return=prompt)

        output = await resolver.resolve(_indexed([_make_config("prompts/bucket/long")]))

        assert len(output.resolved) == 1
        assert output.resolved[0].metadata.name == long_name
        assert len(_issues(output)) == 1
        warning = _issues(output)[0]
        assert isinstance(warning, SkillInitializationException)
        assert warning.severity == "warning"
        assert warning.url == "prompts/bucket/long"
        assert "exceeds 64 characters" in warning.reason

    @pytest.mark.asyncio
    async def test_multiple_warnings_per_skill(self):
        """A skill with both a length and a format violation emits two warnings."""
        bad_name = "-" + "a" * 64  # 65 chars, leading hyphen → both warnings fire
        content = f"---\nname: {bad_name}\ndescription: desc\n---\nBody\n"
        prompt = _make_prompt(content=content)
        resolver = _make_resolver(prompts_get_return=prompt)

        output = await resolver.resolve(_indexed([_make_config("prompts/bucket/iffy")]))

        assert len(output.resolved) == 1
        warnings = [e for e in _issues(output) if e.severity == "warning"]
        assert len(warnings) == 2
        reasons = " | ".join(w.reason for w in warnings)
        assert "exceeds 64 characters" in reasons
        assert "does not match recommended format" in reasons

    @pytest.mark.asyncio
    async def test_warning_and_failure_coexist(self):
        """One URL resolves with a warning; another fails — both reported."""
        long_name = "a" * 65
        ok_with_warning = _make_prompt(
            content=f"---\nname: {long_name}\ndescription: desc\n---\nBody\n"
        )
        broken = _make_prompt(content="no frontmatter here")

        dial_client = MagicMock()
        dial_client.prompts = MagicMock()
        dial_client.prompts.get = AsyncMock(side_effect=[ok_with_warning, broken])
        resolver = DialPromptSkillResolver(dial_client=dial_client)

        output = await resolver.resolve(
            _indexed([_make_config("prompts/bucket/ok"), _make_config("prompts/bucket/broken")])
        )

        assert len(output.resolved) == 1
        assert output.resolved[0].url == "prompts/bucket/ok"
        warnings = [e for e in _issues(output) if e.severity == "warning"]
        errors = [e for e in _issues(output) if e.severity == "error"]
        assert len(warnings) == 1
        assert warnings[0].url == "prompts/bucket/ok"
        assert len(errors) == 1
        assert errors[0].url == "prompts/bucket/broken"

    @pytest.mark.asyncio
    async def test_bom_prefixed_content_resolves(self):
        """Content stored with a leading BOM (common after copy/paste) now parses."""
        content = "﻿" + VALID_SKILL_CONTENT
        prompt = _make_prompt(content=content)
        resolver = _make_resolver(prompts_get_return=prompt)

        output = await resolver.resolve(_indexed([_make_config()]))

        assert len(output.resolved) == 1
        assert output.resolved[0].metadata.name == "my-skill"
        assert _issues(output) == []

    @pytest.mark.asyncio
    async def test_closing_fence_at_eof_resolves(self):
        """Content with no trailing newline after the closing fence now parses."""
        content = "---\nname: my-skill\ndescription: desc\n---"
        prompt = _make_prompt(content=content)
        resolver = _make_resolver(prompts_get_return=prompt)

        output = await resolver.resolve(_indexed([_make_config()]))

        assert len(output.resolved) == 1
        assert output.resolved[0].metadata.name == "my-skill"
        assert _issues(output) == []
