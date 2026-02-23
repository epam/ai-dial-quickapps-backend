from pathlib import Path

import pytest

from quickapp.config.predefined_content_provider import (
    ContentType,
    PredefinedContentProvider,
    PredefinedSettings,
)
from quickapp.skills.agent_skills_provider import AgentSkillsProvider, SkillMetadata


# ---------------------------------------------------------------------------
# _parse_frontmatter unit tests
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    """Tests for AgentSkillsProvider._parse_frontmatter()."""

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
        result = AgentSkillsProvider._parse_frontmatter(content, "my-skill")
        assert result is not None
        assert isinstance(result, SkillMetadata)
        assert result.name == "my-skill"
        assert result.description == "A test skill"
        assert result.license == "MIT"
        assert result.compatibility == ">=1.0"
        assert result.metadata == {"version": "1.0"}
        assert result.allowed_tools == ["tool_a", "tool_b"]

    def test_missing_name_returns_none(self):
        content = "---\ndescription: A skill without name\n---\nBody\n"
        assert AgentSkillsProvider._parse_frontmatter(content, "test") is None

    def test_missing_description_returns_none(self):
        content = "---\nname: my-skill\n---\nBody\n"
        assert AgentSkillsProvider._parse_frontmatter(content, "test") is None

    def test_name_exceeds_64_chars_returns_none(self):
        long_name = "a" * 65
        content = f"---\nname: {long_name}\ndescription: desc\n---\nBody\n"
        assert AgentSkillsProvider._parse_frontmatter(content, "test") is None

    def test_consecutive_hyphens_returns_none(self):
        content = "---\nname: my--skill\ndescription: desc\n---\nBody\n"
        assert AgentSkillsProvider._parse_frontmatter(content, "test") is None

    def test_leading_hyphen_returns_none(self):
        content = "---\nname: -my-skill\ndescription: desc\n---\nBody\n"
        assert AgentSkillsProvider._parse_frontmatter(content, "test") is None

    def test_trailing_hyphen_returns_none(self):
        content = "---\nname: my-skill-\ndescription: desc\n---\nBody\n"
        assert AgentSkillsProvider._parse_frontmatter(content, "test") is None

    def test_invalid_yaml_returns_none(self):
        content = "---\n: [invalid yaml\n---\nBody\n"
        assert AgentSkillsProvider._parse_frontmatter(content, "test") is None

    def test_non_dict_yaml_returns_none(self):
        content = "---\n- item1\n- item2\n---\nBody\n"
        assert AgentSkillsProvider._parse_frontmatter(content, "test") is None

    def test_allowed_tools_as_string_normalized_to_list(self):
        content = "---\nname: my-skill\ndescription: desc\nallowed-tools: tool1 tool2\n---\nBody\n"
        result = AgentSkillsProvider._parse_frontmatter(content, "test")
        assert result is not None
        assert result.allowed_tools == ["tool1", "tool2"]

    def test_allowed_tools_as_list_kept(self):
        content = (
            "---\nname: my-skill\ndescription: desc\n"
            "allowed-tools:\n  - tool1\n  - tool2\n---\nBody\n"
        )
        result = AgentSkillsProvider._parse_frontmatter(content, "test")
        assert result is not None
        assert result.allowed_tools == ["tool1", "tool2"]

    def test_description_exceeds_1024_chars_returns_none(self):
        long_desc = "x" * 1025
        content = f"---\nname: my-skill\ndescription: {long_desc}\n---\nBody\n"
        assert AgentSkillsProvider._parse_frontmatter(content, "test") is None

    def test_no_frontmatter_returns_none(self):
        content = "Just some text without frontmatter"
        assert AgentSkillsProvider._parse_frontmatter(content, "test") is None


# ---------------------------------------------------------------------------
# _generate_xml unit tests
# ---------------------------------------------------------------------------


class TestGenerateXml:
    """Tests for AgentSkillsProvider._generate_xml()."""

    def _make_provider_for_xml(self) -> AgentSkillsProvider:
        """Create a minimal provider with builtin content for calling _generate_xml."""
        provider = PredefinedContentProvider(PredefinedSettings())
        return AgentSkillsProvider(provider)

    def test_empty_list_returns_empty_string(self):
        asp = self._make_provider_for_xml()
        assert asp._generate_xml([]) == ""

    def test_single_skill_required_fields_only(self):
        asp = self._make_provider_for_xml()
        skill = SkillMetadata(name="test-skill", description="A test skill")
        xml = asp._generate_xml([skill])
        assert "<available_skills>" in xml
        assert "<name>test-skill</name>" in xml
        assert "<description>A test skill</description>" in xml
        assert "</available_skills>" in xml

    def test_skill_with_all_optional_fields(self):
        asp = self._make_provider_for_xml()
        skill = SkillMetadata(
            name="full-skill",
            description="Full skill",
            license="MIT",
            compatibility=">=1.0",
            metadata={"version": "2.0"},
            allowed_tools=["tool_a", "tool_b"],
        )
        xml = asp._generate_xml([skill])
        assert "<license>MIT</license>" in xml
        assert "<compatibility>&gt;=1.0</compatibility>" in xml
        assert "<allowed_tools>tool_a tool_b</allowed_tools>" in xml
        assert '<entry key="version">2.0</entry>' in xml

    def test_xml_escaping_of_special_characters(self):
        asp = self._make_provider_for_xml()
        skill = SkillMetadata(name="esc-skill", description="Use <b>&amp;</b> 'quotes'")
        xml = asp._generate_xml([skill])
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

        settings = PredefinedSettings(extra_paths=str(tmp_path))
        provider = PredefinedContentProvider(settings)
        asp = AgentSkillsProvider(provider)

        xml = asp.get_skills_xml()
        assert "my-valid-skill" in xml

    def test_name_mismatch_skips_skill(self, tmp_path: Path):
        skill_dir = tmp_path / "skills" / "dir-name"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: different-name\ndescription: Mismatch\n---\nBody\n"
        )

        settings = PredefinedSettings(extra_paths=str(tmp_path))
        provider = PredefinedContentProvider(settings)
        asp = AgentSkillsProvider(provider)

        xml = asp.get_skills_xml()
        assert "different-name" not in xml
        assert "dir-name" not in xml

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

        settings = PredefinedSettings(extra_paths=str(tmp_path))
        provider = PredefinedContentProvider(settings)
        asp = AgentSkillsProvider(provider)

        xml = asp.get_skills_xml()
        assert "good-skill" in xml
        assert "bad-skill" not in xml


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
