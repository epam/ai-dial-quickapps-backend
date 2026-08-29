from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.skills._exceptions import SkillFileNotFound, SkillFileTooLarge
from quickapp.skills._settings import SkillsSettings
from quickapp.skills._skill import Skill, SkillFileContent, SkillFileEntry
from quickapp.skills._skill_reader_tool import _SkillReaderTool
from quickapp.skills._skills_registry import SkillsRegistry


def _make_tool(
    manifest: str = "---\nname: s\ndescription: d\n---\nBody",
    files: list[str] | None = None,
    truncated: bool = False,
    read_file: AsyncMock | None = None,
    settings: SkillsSettings | None = None,
) -> _SkillReaderTool:
    skill = MagicMock(spec=Skill)
    skill.read_manifest.return_value = manifest
    skill.list_files.return_value = [SkillFileEntry(path=p) for p in files or []]
    skill.inventory_truncated = truncated
    skill.read_file = read_file or AsyncMock()
    registry = MagicMock(spec=SkillsRegistry)
    registry.get_skill.return_value = skill
    return _SkillReaderTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=MagicMock(),
        perf_timer=MagicMock(),
        skills_registry=registry,
        settings=settings or SkillsSettings(),
    )


async def _run(tool: _SkillReaderTool, **kwargs) -> str:
    result = await tool._run_in_stage_async(**kwargs)
    return result.content


class TestManifestMode:
    @pytest.mark.asyncio
    async def test_returns_the_manifest_when_no_file_path_is_given(self):
        content = await _run(_make_tool(manifest="# Instructions"), skill_name="s")

        assert content == "# Instructions"

    @pytest.mark.asyncio
    async def test_appends_the_inventory_when_the_skill_bundles_files(self):
        tool = _make_tool(manifest="# Instructions", files=["references/a.md", "scripts/b.py"])

        content = await _run(tool, skill_name="s")

        assert "# Instructions" in content
        assert "<skill_files>\nreferences/a.md\nscripts/b.py\n</skill_files>" in content

    @pytest.mark.asyncio
    async def test_a_truncated_inventory_says_so(self):
        tool = _make_tool(files=["references/a.md"], truncated=True)

        assert "inventory truncated" in await _run(tool, skill_name="s")

    @pytest.mark.asyncio
    async def test_skill_md_is_equivalent_to_omitting_the_parameter(self):
        tool = _make_tool(manifest="# Instructions")

        assert await _run(tool, skill_name="s", file_path="SKILL.md") == "# Instructions"

    @pytest.mark.asyncio
    async def test_blank_file_path_is_treated_as_a_manifest_read(self):
        tool = _make_tool(manifest="# Instructions")

        assert await _run(tool, skill_name="s", file_path="  ") == "# Instructions"

    @pytest.mark.asyncio
    async def test_missing_skill_name_is_reported(self):
        assert "Missing required parameter" in await _run(_make_tool(), skill_name=None)


class TestFileMode:
    @pytest.mark.asyncio
    async def test_returns_the_requested_file(self):
        read_file = AsyncMock(
            return_value=SkillFileContent(
                path="references/a.md", text="# Matrix", content_type="text/markdown"
            )
        )
        tool = _make_tool(files=["references/a.md"], read_file=read_file)

        content = await _run(tool, skill_name="s", file_path="references/a.md")

        assert content == "# Matrix"
        read_file.assert_awaited_once_with("references/a.md")

    @pytest.mark.asyncio
    async def test_path_is_normalized_before_the_read(self):
        read_file = AsyncMock(
            return_value=SkillFileContent(path="refs/a.md", text="x", content_type="text/markdown")
        )
        tool = _make_tool(read_file=read_file)

        await _run(tool, skill_name="s", file_path="./refs//a.md")

        read_file.assert_awaited_once_with("refs/a.md")

    @pytest.mark.asyncio
    async def test_dot_dot_is_rejected_rather_than_resolved(self):
        """Even a `..` that would resolve back inside the skill is refused —
        the guardrail is a shape check, not a resolution."""
        read_file = AsyncMock()
        tool = _make_tool(read_file=read_file)

        content = await _run(tool, skill_name="s", file_path="refs/../a.md")

        assert "Error" in content
        read_file.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_escaping_path_is_rejected_before_any_read(self):
        read_file = AsyncMock()
        tool = _make_tool(read_file=read_file)

        content = await _run(tool, skill_name="s", file_path="../../etc/passwd")

        assert "Error" in content
        read_file.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_file_lists_what_the_skill_does_contain(self):
        read_file = AsyncMock(side_effect=SkillFileNotFound("'nope.md' is not a file"))
        tool = _make_tool(files=["references/a.md", "scripts/b.py"], read_file=read_file)

        content = await _run(tool, skill_name="s", file_path="nope.md")

        assert "nope.md" in content
        assert "references/a.md" in content
        assert "scripts/b.py" in content

    @pytest.mark.asyncio
    async def test_missing_file_hint_flags_a_truncated_inventory(self):
        read_file = AsyncMock(side_effect=SkillFileNotFound("no such file"))
        tool = _make_tool(files=["references/a.md"], truncated=True, read_file=read_file)

        content = await _run(tool, skill_name="s", file_path="nope.md")

        assert "the skill has more files" in content

    @pytest.mark.asyncio
    async def test_oversized_file_reports_the_limit_rather_than_truncating(self):
        read_file = AsyncMock(side_effect=SkillFileTooLarge("big.md", 100, 50))
        tool = _make_tool(read_file=read_file)

        content = await _run(tool, skill_name="s", file_path="big.md")

        assert "100 bytes" in content
        assert "50-byte limit" in content


class TestCombinedSizeCap:
    """The manifest is capped on its own; the inventory appended to it must not
    push the single tool result past the same ceiling - `read_skill` is excluded
    from offload, so nothing downstream would trim it."""

    @pytest.mark.asyncio
    async def test_inventory_is_trimmed_to_the_remaining_budget(self):
        manifest = "x" * 90
        tool = _make_tool(
            manifest=manifest,
            files=[f"references/file-{i:03d}.md" for i in range(50)],
            settings=SkillsSettings(file_max_bytes=120),
        )

        content = await _run(tool, skill_name="s")

        assert len(content.encode("utf-8")) < 200
        assert "inventory truncated" in content

    @pytest.mark.asyncio
    async def test_a_manifest_at_the_cap_drops_the_inventory_entirely(self):
        tool = _make_tool(
            manifest="x" * 100,
            files=["references/a.md"],
            settings=SkillsSettings(file_max_bytes=100),
        )

        assert await _run(tool, skill_name="s") == "x" * 100

    @pytest.mark.asyncio
    async def test_a_normal_skill_is_untouched(self):
        tool = _make_tool(manifest="# Instructions", files=["references/a.md"])

        content = await _run(tool, skill_name="s")

        assert "<skill_files>\nreferences/a.md\n</skill_files>" in content
        assert "inventory truncated" not in content
