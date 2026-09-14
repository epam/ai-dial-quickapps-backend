from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.skills._exceptions import SkillFileNotFoundError, SkillFilesNotSupportedError
from quickapp.skills._skill_reader_tool import _SkillReaderTool
from quickapp.skills._tool_configs import SKILL_READER_TOOL_CONFIG


def _make_tool(registry: MagicMock) -> _SkillReaderTool:
    return _SkillReaderTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=SKILL_READER_TOOL_CONFIG,
        perf_timer=MagicMock(),
        skills_registry=registry,
    )


def _make_registry() -> MagicMock:
    registry = MagicMock()
    registry.get_skill_content.return_value = "# Manifest"
    registry.read_skill_file = AsyncMock(return_value="# Bundled file")
    return registry


class TestSkillReaderTool:

    @pytest.mark.asyncio
    async def test_without_file_path_reads_the_manifest(self):
        registry = _make_registry()
        tool = _make_tool(registry)

        result = await tool._run_in_stage_async(skill_name="refunds")

        assert result.content == "# Manifest"
        registry.read_skill_file.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_with_file_path_reads_the_bundled_file(self):
        registry = _make_registry()
        tool = _make_tool(registry)

        result = await tool._run_in_stage_async(skill_name="refunds", file_path="references/eu.md")

        assert result.content == "# Bundled file"
        registry.read_skill_file.assert_awaited_once_with("refunds", "references/eu.md")
        registry.get_skill_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_file_path_falls_back_to_the_manifest(self):
        registry = _make_registry()
        tool = _make_tool(registry)

        result = await tool._run_in_stage_async(skill_name="refunds", file_path="")

        assert result.content == "# Manifest"

    @pytest.mark.asyncio
    async def test_missing_skill_name_is_reported(self):
        tool = _make_tool(_make_registry())

        result = await tool._run_in_stage_async(skill_name=None)

        assert "Missing required parameter: skill_name" in result.content

    @pytest.mark.asyncio
    async def test_unavailable_file_hands_the_inventory_back_to_the_model(self):
        registry = _make_registry()
        registry.read_skill_file = AsyncMock(
            side_effect=SkillFileNotFoundError("refunds", "assets/logo.png", ["references/eu.md"])
        )
        tool = _make_tool(registry)

        result = await tool._run_in_stage_async(skill_name="refunds", file_path="assets/logo.png")

        assert "is not available in skill 'refunds'" in result.content
        assert "references/eu.md" in result.content

    @pytest.mark.asyncio
    async def test_source_without_files_is_explained(self):
        registry = _make_registry()
        registry.read_skill_file = AsyncMock(side_effect=SkillFilesNotSupportedError("predef"))
        tool = _make_tool(registry)

        result = await tool._run_in_stage_async(skill_name="predef", file_path="a.md")

        assert "has no bundled files" in result.content


class TestToolSchema:

    def test_file_path_is_optional(self):
        parameters = SKILL_READER_TOOL_CONFIG.open_ai_tool.function.parameters

        assert "file_path" in parameters.properties
        assert parameters.required == ["skill_name"]
