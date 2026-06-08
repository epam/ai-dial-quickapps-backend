from pathlib import Path

import pytest

from quickapp.config.predefined_content_provider import (
    PredefinedContentProvider,
    PredefinedSettings,
)
from quickapp.skills._exceptions import SkillValidationError
from quickapp.skills._frontmatter import parse_frontmatter
from quickapp.skills._skill_metadata import ParsedSkill, SkillMetadata
from quickapp.skills._xml import generate_skills_xml
from quickapp.skills.agent_skills_provider import AgentSkillsProvider

# ---------------------------------------------------------------------------
# parse_frontmatter unit tests
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    """Tests for parse_frontmatter()."""

    def test_valid_skill_all_fields(self):
        content = (
            "---\n"
            "name: my-skill\n"
            "description: A test skill\n"
            "license: MIT\n"
            "compatibility: '>=1.0'\n"
            "metadata:\n"
            "  version: '1.0'\n"
            "allowed-tools:\n"
            "  - tool_a\n"
            "  - tool_b\n"
            "---\n"
            "Body content\n"
        )
        result = parse_frontmatter(content, "my-skill")
        assert isinstance(result, ParsedSkill)
        assert result.warnings == []
        meta = result.metadata
        assert isinstance(meta, SkillMetadata)
        assert meta.name == "my-skill"
        assert meta.description == "A test skill"
        assert meta.license == "MIT"
        assert meta.compatibility == ">=1.0"
        assert meta.metadata == {"version": "1.0"}
        assert meta.allowed_tools == ["tool_a", "tool_b"]

    def test_missing_name_raises(self):
        content = "---\ndescription: A skill without name\n---\nBody\n"
        with pytest.raises(SkillValidationError):
            parse_frontmatter(content, "test")

    def test_missing_description_raises(self):
        content = "---\nname: my-skill\n---\nBody\n"
        with pytest.raises(SkillValidationError):
            parse_frontmatter(content, "test")

    def test_name_exceeds_64_chars_warns(self):
        long_name = "a" * 65
        content = f"---\nname: {long_name}\ndescription: desc\n---\nBody\n"
        result = parse_frontmatter(content, "test")
        assert result.metadata.name == long_name
        assert any("exceeds 64 characters" in w for w in result.warnings)

    def test_consecutive_hyphens_warns(self):
        content = "---\nname: my--skill\ndescription: desc\n---\nBody\n"
        result = parse_frontmatter(content, "test")
        assert result.metadata.name == "my--skill"
        assert any("does not match recommended format" in w for w in result.warnings)

    def test_leading_hyphen_warns(self):
        content = "---\nname: -my-skill\ndescription: desc\n---\nBody\n"
        result = parse_frontmatter(content, "test")
        assert result.metadata.name == "-my-skill"
        assert any("does not match recommended format" in w for w in result.warnings)

    def test_trailing_hyphen_warns(self):
        content = "---\nname: my-skill-\ndescription: desc\n---\nBody\n"
        result = parse_frontmatter(content, "test")
        assert result.metadata.name == "my-skill-"
        assert any("does not match recommended format" in w for w in result.warnings)

    def test_invalid_yaml_raises(self):
        content = "---\n: [invalid yaml\n---\nBody\n"
        with pytest.raises(SkillValidationError):
            parse_frontmatter(content, "test")

    def test_non_dict_yaml_raises(self):
        content = "---\n- item1\n- item2\n---\nBody\n"
        with pytest.raises(SkillValidationError):
            parse_frontmatter(content, "test")

    def test_allowed_tools_as_string_normalized_to_list(self):
        content = "---\nname: my-skill\ndescription: desc\nallowed-tools: tool1 tool2\n---\nBody\n"
        result = parse_frontmatter(content, "test")
        assert result.metadata.allowed_tools == ["tool1", "tool2"]

    def test_allowed_tools_as_list_kept(self):
        content = (
            "---\nname: my-skill\ndescription: desc\n"
            "allowed-tools:\n  - tool1\n  - tool2\n---\nBody\n"
        )
        result = parse_frontmatter(content, "test")
        assert result.metadata.allowed_tools == ["tool1", "tool2"]

    def test_description_exceeds_1024_chars_warns(self):
        long_desc = "x" * 1025
        content = f"---\nname: my-skill\ndescription: {long_desc}\n---\nBody\n"
        result = parse_frontmatter(content, "test")
        assert result.metadata.description == long_desc
        assert any("Description exceeds 1024" in w for w in result.warnings)

    def test_compatibility_exceeds_500_chars_warns(self):
        long_compat = "x" * 501
        content = (
            f"---\nname: my-skill\ndescription: desc\n" f"compatibility: {long_compat}\n---\nBody\n"
        )
        result = parse_frontmatter(content, "test")
        assert result.metadata.compatibility == long_compat
        assert any("Compatibility exceeds 500" in w for w in result.warnings)

    def test_no_frontmatter_raises(self):
        content = "Just some text without frontmatter"
        with pytest.raises(SkillValidationError):
            parse_frontmatter(content, "test")

    def test_error_carries_source_id_and_reason(self):
        content = "No frontmatter"
        with pytest.raises(SkillValidationError) as exc_info:
            parse_frontmatter(content, "my-source")
        assert exc_info.value.source_id == "my-source"
        assert "No YAML frontmatter found" in exc_info.value.reason

    # ---- lenient regex cases --------------------------------------------

    def test_bom_prefixed_parses(self):
        content = "﻿---\nname: my-skill\ndescription: desc\n---\nBody\n"
        result = parse_frontmatter(content, "test")
        assert result.metadata.name == "my-skill"

    def test_leading_whitespace_parses(self):
        content = "   \n---\nname: my-skill\ndescription: desc\n---\nBody\n"
        result = parse_frontmatter(content, "test")
        assert result.metadata.name == "my-skill"

    def test_leading_blank_line_parses(self):
        content = "\n---\nname: my-skill\ndescription: desc\n---\nBody\n"
        result = parse_frontmatter(content, "test")
        assert result.metadata.name == "my-skill"

    def test_closing_fence_at_eof_parses(self):
        content = "---\nname: my-skill\ndescription: desc\n---"
        result = parse_frontmatter(content, "test")
        assert result.metadata.name == "my-skill"

    def test_crlf_line_endings_parse(self):
        content = "---\r\nname: my-skill\r\ndescription: desc\r\n---\r\nBody\r\n"
        result = parse_frontmatter(content, "test")
        assert result.metadata.name == "my-skill"

    # ---- YAML quote-retry ----------------------------------------------

    def test_unquoted_colon_in_description_recovered(self):
        content = (
            "---\n"
            "name: my-skill\n"
            "description: Use when: the user asks about PDFs\n"
            "---\n"
            "Body\n"
        )
        result = parse_frontmatter(content, "test")
        assert result.metadata.description == "Use when: the user asks about PDFs"
        assert any("YAML repaired" in w for w in result.warnings)

    def test_unrecoverable_yaml_still_raises(self):
        # `description: With: colon` triggers the quote-repair, but `: [broken`
        # is still broken after the repair — the second parse fails too.
        content = "---\nname: x\ndescription: With: colon\n: [broken\n---\nBody\n"
        with pytest.raises(SkillValidationError, match="Failed to parse YAML frontmatter"):
            parse_frontmatter(content, "test")


# ---------------------------------------------------------------------------
# generate_skills_xml unit tests
# ---------------------------------------------------------------------------


class TestGenerateSkillsXml:
    """Tests for generate_skills_xml()."""

    def test_empty_list_returns_empty_string(self):
        assert generate_skills_xml([]) == ""

    def test_single_skill_required_fields_only(self):
        skill = SkillMetadata(name="test-skill", description="A test skill")
        xml = generate_skills_xml([skill])
        assert "<available_skills>" in xml
        assert "<name>test-skill</name>" in xml
        assert "<description>A test skill</description>" in xml
        assert "</available_skills>" in xml

    def test_skill_with_all_optional_fields(self):
        skill = SkillMetadata(
            name="full-skill",
            description="Full skill",
            license="MIT",
            compatibility=">=1.0",
            metadata={"version": "2.0"},
            allowed_tools=["tool_a", "tool_b"],
        )
        xml = generate_skills_xml([skill])
        assert "<license>MIT</license>" in xml
        assert "<compatibility>&gt;=1.0</compatibility>" in xml
        assert "<allowed_tools>tool_a tool_b</allowed_tools>" in xml
        assert '<entry key="version">2.0</entry>' in xml

    def test_xml_escaping_of_special_characters(self):
        skill = SkillMetadata(name="esc-skill", description="Use <b>&amp;</b> 'quotes'")
        xml = generate_skills_xml([skill])
        assert "&lt;b&gt;&amp;amp;&lt;/b&gt;" in xml
        assert "&apos;quotes&apos;" in xml


# ---------------------------------------------------------------------------
# Integration tests (via constructor with real provider)
# ---------------------------------------------------------------------------


class TestAgentSkillsProviderIntegration:
    """Integration tests using a real PredefinedContentProvider."""

    def test_valid_skill_in_directory_layout(self, tmp_path: Path):
        skill_dir = tmp_path / "skills" / "my-valid-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-valid-skill\ndescription: Valid skill\n---\nBody\n"
        )

        settings = PredefinedSettings(extra_paths=[str(tmp_path)])
        provider = PredefinedContentProvider(settings)
        asp = AgentSkillsProvider(provider)

        skills = asp.get_all_skills()
        assert any(s.name == "my-valid-skill" for s in skills)

    def test_name_mismatch_loads_anyway(self, tmp_path: Path):
        skill_dir = tmp_path / "skills" / "dir-name"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: different-name\ndescription: Mismatch\n---\nBody\n"
        )

        settings = PredefinedSettings(extra_paths=[str(tmp_path)])
        provider = PredefinedContentProvider(settings)
        asp = AgentSkillsProvider(provider)

        skill_names = [s.name for s in asp.get_all_skills()]
        assert "different-name" in skill_names

    def test_mixed_valid_invalid_skills(self, tmp_path: Path):
        # Valid skill
        valid_dir = tmp_path / "skills" / "good-skill"
        valid_dir.mkdir(parents=True)
        (valid_dir / "SKILL.md").write_text(
            "---\nname: good-skill\ndescription: Good one\n---\nBody\n"
        )

        # Invalid skill (no description)
        invalid_dir = tmp_path / "skills" / "bad-skill"
        invalid_dir.mkdir(parents=True)
        (invalid_dir / "SKILL.md").write_text("---\nname: bad-skill\n---\nBody\n")

        settings = PredefinedSettings(extra_paths=[str(tmp_path)])
        provider = PredefinedContentProvider(settings)
        asp = AgentSkillsProvider(provider)

        skill_names = [s.name for s in asp.get_all_skills()]
        assert "good-skill" in skill_names
        assert "bad-skill" not in skill_names


# ---------------------------------------------------------------------------
# get_skill_content tests
# ---------------------------------------------------------------------------


class TestGetSkillContent:
    """Tests for AgentSkillsProvider.get_skill_content()."""

    def test_known_skill_returns_content(self):
        provider = PredefinedContentProvider(PredefinedSettings())
        asp = AgentSkillsProvider(provider)

        content = asp.get_skill_content("tool-call-file-parameter-formatting")
        assert isinstance(content, str)
        assert len(content) > 0

    def test_unknown_skill_raises_file_not_found(self):
        provider = PredefinedContentProvider(PredefinedSettings())
        asp = AgentSkillsProvider(provider)

        with pytest.raises(FileNotFoundError, match="Skill not found"):
            asp.get_skill_content("nonexistent-skill")
