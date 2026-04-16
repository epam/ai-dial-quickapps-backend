from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.skills._exceptions import SkillResolutionWarning
from quickapp.skills._skills_registry import SkillsRegistry
from quickapp.skills.agent_skills_provider import SkillMetadata


def _make_predefined_provider(
    skills: list[SkillMetadata] | None = None,
    contents: dict[str, str] | None = None,
) -> MagicMock:
    provider = MagicMock()
    provider.get_all_skills.return_value = skills or []
    provider.get_all_skill_contents.return_value = contents or {}
    return provider


def _make_config_provider(skills_config: list | None = None) -> MagicMock:
    config = MagicMock()
    config.skills = skills_config
    provider = MagicMock()
    provider.get.return_value = config
    return provider


def _make_stage_provider() -> MagicMock:
    stage = MagicMock()
    stage.open = MagicMock()
    stage.append_name = MagicMock()
    stage.append_content = MagicMock()
    stage.close = MagicMock()
    provider = MagicMock()
    provider.get.return_value = stage
    return provider


def _skill(name: str, description: str = "A skill") -> SkillMetadata:
    return SkillMetadata(name=name, description=description)


class TestSkillsRegistryNoPResolver:
    """Tests when no DialPromptSkillResolver is available (preview off)."""

    @pytest.mark.asyncio
    async def test_returns_predefined_only(self):
        predefined = [_skill("predefined-skill")]
        contents = {"predefined-skill": "# Predefined\nContent here"}
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(predefined, contents),
            config_provider=_make_config_provider(),
            stage_provider=_make_stage_provider(),
            dial_prompt_resolver=None,
        )

        xml = await registry.get_prompt_part()

        assert "predefined-skill" in xml
        assert "<available_skills>" in xml

    @pytest.mark.asyncio
    async def test_get_skill_content_returns_predefined(self):
        contents = {"my-skill": "# My Skill\nContent"}
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider([_skill("my-skill")], contents),
            config_provider=_make_config_provider(),
            stage_provider=_make_stage_provider(),
            dial_prompt_resolver=None,
        )

        content = await registry.get_skill_content("my-skill")
        assert content == "# My Skill\nContent"

    @pytest.mark.asyncio
    async def test_get_skill_content_unknown_raises(self):
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(),
            config_provider=_make_config_provider(),
            stage_provider=_make_stage_provider(),
            dial_prompt_resolver=None,
        )

        with pytest.raises(FileNotFoundError, match="Skill not found"):
            await registry.get_skill_content("nonexistent")

    @pytest.mark.asyncio
    async def test_empty_predefined_returns_empty_xml(self):
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(),
            config_provider=_make_config_provider(),
            stage_provider=_make_stage_provider(),
            dial_prompt_resolver=None,
        )

        xml = await registry.get_prompt_part()
        assert xml == ""


class TestSkillsRegistryWithResolver:
    """Tests when DialPromptSkillResolver is available."""

    @pytest.mark.asyncio
    async def test_merges_predefined_and_dial_prompt_skills(self):
        predefined = [_skill("predefined")]
        predefined_contents = {"predefined": "Predefined content"}

        dial_metadata = _skill("dial-skill", "From DIAL")
        dial_content = "DIAL skill content"

        resolver = AsyncMock()
        resolver.resolve.return_value = ([(dial_metadata, dial_content)], [])

        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(predefined, predefined_contents),
            config_provider=_make_config_provider(skills_config=["some-config"]),
            stage_provider=_make_stage_provider(),
            dial_prompt_resolver=resolver,
        )

        xml = await registry.get_prompt_part()

        assert "predefined" in xml
        assert "dial-skill" in xml

    @pytest.mark.asyncio
    async def test_predefined_wins_on_name_collision(self):
        predefined = [_skill("shared-name", "Predefined version")]
        predefined_contents = {"shared-name": "Predefined content"}

        dial_metadata = _skill("shared-name", "DIAL version")
        dial_content = "DIAL content"

        resolver = AsyncMock()
        resolver.resolve.return_value = ([(dial_metadata, dial_content)], [])

        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(predefined, predefined_contents),
            config_provider=_make_config_provider(skills_config=["some-config"]),
            stage_provider=_make_stage_provider(),
            dial_prompt_resolver=resolver,
        )

        xml = await registry.get_prompt_part()
        content = await registry.get_skill_content("shared-name")

        assert "Predefined version" in xml
        assert content == "Predefined content"

    @pytest.mark.asyncio
    async def test_resolver_failure_falls_back_to_predefined(self):
        predefined = [_skill("safe-skill")]
        predefined_contents = {"safe-skill": "Safe content"}

        resolver = AsyncMock()
        resolver.resolve.side_effect = RuntimeError("DIAL Core is down")

        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(predefined, predefined_contents),
            config_provider=_make_config_provider(skills_config=["some-config"]),
            stage_provider=_make_stage_provider(),
            dial_prompt_resolver=resolver,
        )

        xml = await registry.get_prompt_part()

        assert "safe-skill" in xml

    @pytest.mark.asyncio
    async def test_lazy_resolution_only_resolves_once(self):
        resolver = AsyncMock()
        resolver.resolve.return_value = ([], [])

        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(),
            config_provider=_make_config_provider(skills_config=["config"]),
            stage_provider=_make_stage_provider(),
            dial_prompt_resolver=resolver,
        )

        await registry.get_prompt_part()
        await registry.get_prompt_part()

        resolver.resolve.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_skill_content_for_dial_prompt_skill(self):
        dial_metadata = _skill("dial-only")
        dial_content = "DIAL prompt skill content"

        resolver = AsyncMock()
        resolver.resolve.return_value = ([(dial_metadata, dial_content)], [])

        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(),
            config_provider=_make_config_provider(skills_config=["some-config"]),
            stage_provider=_make_stage_provider(),
            dial_prompt_resolver=resolver,
        )

        content = await registry.get_skill_content("dial-only")
        assert content == "DIAL prompt skill content"

    @pytest.mark.asyncio
    async def test_no_skill_configs_skips_resolver(self):
        resolver = AsyncMock()

        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(),
            config_provider=_make_config_provider(skills_config=None),
            stage_provider=_make_stage_provider(),
            dial_prompt_resolver=resolver,
        )

        await registry.get_prompt_part()

        resolver.resolve.assert_not_awaited()


class TestSkillsRegistryStageWarnings:
    """Tests for stage-based warning display."""

    @pytest.mark.asyncio
    async def test_warnings_open_stage(self):
        resolver = AsyncMock()
        resolver.resolve.return_value = (
            [],
            [SkillResolutionWarning(url="prompts/b/s", reason="fetch failed")],
        )

        stage_provider = _make_stage_provider()
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(),
            config_provider=_make_config_provider(skills_config=["cfg"]),
            stage_provider=stage_provider,
            dial_prompt_resolver=resolver,
        )

        await registry.get_prompt_part()

        stage = stage_provider.get.return_value
        stage.open.assert_called_once()
        stage.append_name.assert_called_once()
        stage.append_content.assert_called_once()
        content_arg = stage.append_content.call_args[0][0]
        assert "prompts/b/s" in content_arg
        assert "fetch failed" in content_arg
        stage.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_warnings_no_stage(self):
        resolver = AsyncMock()
        resolver.resolve.return_value = ([], [])

        stage_provider = _make_stage_provider()
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(),
            config_provider=_make_config_provider(skills_config=["cfg"]),
            stage_provider=stage_provider,
            dial_prompt_resolver=resolver,
        )

        await registry.get_prompt_part()

        stage_provider.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_predefined_collision_opens_stage(self):
        predefined = [_skill("shared")]
        predefined_contents = {"shared": "Predefined content"}

        dial_metadata = _skill("shared", "DIAL version")
        dial_content = "DIAL content"

        resolver = AsyncMock()
        resolver.resolve.return_value = ([(dial_metadata, dial_content)], [])

        stage_provider = _make_stage_provider()
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(predefined, predefined_contents),
            config_provider=_make_config_provider(skills_config=["cfg"]),
            stage_provider=stage_provider,
            dial_prompt_resolver=resolver,
        )

        await registry.get_prompt_part()

        stage = stage_provider.get.return_value
        stage.open.assert_called_once()
        content_arg = stage.append_content.call_args[0][0]
        assert "shared" in content_arg
        assert "predefined" in content_arg.lower()

    @pytest.mark.asyncio
    async def test_catastrophic_failure_opens_stage(self):
        resolver = AsyncMock()
        resolver.resolve.side_effect = RuntimeError("DIAL Core is down")

        stage_provider = _make_stage_provider()
        registry = SkillsRegistry(
            predefined_provider=_make_predefined_provider(),
            config_provider=_make_config_provider(skills_config=["cfg"]),
            stage_provider=stage_provider,
            dial_prompt_resolver=resolver,
        )

        await registry.get_prompt_part()

        stage = stage_provider.get.return_value
        stage.open.assert_called_once()
        content_arg = stage.append_content.call_args[0][0]
        assert "DIAL Core is down" in content_arg
