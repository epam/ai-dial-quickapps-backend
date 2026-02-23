from pathlib import Path

import pytest

from quickapp.config.predefined_content_provider import (
    ContentType,
    PredefinedContentProvider,
    PredefinedSettings,
)


@pytest.fixture(scope="module")
def builtin_provider() -> PredefinedContentProvider:
    """Shared provider with default (built-in only) settings."""
    return PredefinedContentProvider(PredefinedSettings())


class TestBuiltinLayer:
    """Tests that the built-in layer is auto-detected and lists expected content."""

    def test_lists_builtin_prompts(self, builtin_provider: PredefinedContentProvider):
        names = builtin_provider.list_names(ContentType.PROMPT)
        assert "anthropic_prompt" in names
        assert "gemini_prompt" in names
        assert "gpt_prompt" in names

    def test_lists_builtin_tools(self, builtin_provider: PredefinedContentProvider):
        names = builtin_provider.list_names(ContentType.TOOL)
        assert "dial_rag" in names
        assert "image_generation" in names
        assert "py_interpreter" in names
        assert "web_search" in names

    def test_lists_builtin_toolsets(self, builtin_provider: PredefinedContentProvider):
        names = builtin_provider.list_names(ContentType.TOOLSET)
        assert "chathub" in names
        assert "location" in names
        assert "py_interpreter" in names
        assert "weather" in names

    def test_lists_builtin_skills(self, builtin_provider: PredefinedContentProvider):
        names = builtin_provider.list_names(ContentType.SKILL)
        assert "tool-call-file-parameter-formatting" in names


class TestReadText:
    """Tests for read_text()."""

    def test_read_prompt_returns_string(self, builtin_provider: PredefinedContentProvider):
        content = builtin_provider.read_text(ContentType.PROMPT, "gpt_prompt")
        assert isinstance(content, str)
        assert len(content) > 0

    def test_read_skill_returns_string(self, builtin_provider: PredefinedContentProvider):
        content = builtin_provider.read_text(ContentType.SKILL, "tool-call-file-parameter-formatting")
        assert isinstance(content, str)
        assert len(content) > 0

    def test_read_text_on_json_type_raises_type_error(
        self, builtin_provider: PredefinedContentProvider
    ):
        with pytest.raises(TypeError, match="read_text.*not supported.*tool"):
            builtin_provider.read_text(ContentType.TOOL, "dial_rag")

    def test_read_text_on_toolset_raises_type_error(
        self, builtin_provider: PredefinedContentProvider
    ):
        with pytest.raises(TypeError, match="read_text.*not supported.*toolset"):
            builtin_provider.read_text(ContentType.TOOLSET, "chathub")

    def test_missing_name_raises_key_error(self, builtin_provider: PredefinedContentProvider):
        with pytest.raises(KeyError, match="not found"):
            builtin_provider.read_text(ContentType.PROMPT, "nonexistent_prompt")


class TestReadJson:
    """Tests for read_json()."""

    def test_read_tool_returns_dict(self, builtin_provider: PredefinedContentProvider):
        content = builtin_provider.read_json(ContentType.TOOL, "dial_rag")
        assert isinstance(content, dict)

    def test_read_toolset_returns_dict(self, builtin_provider: PredefinedContentProvider):
        content = builtin_provider.read_json(ContentType.TOOLSET, "chathub")
        assert isinstance(content, dict)

    def test_read_json_on_text_type_raises_type_error(
        self, builtin_provider: PredefinedContentProvider
    ):
        with pytest.raises(TypeError, match="read_json.*not supported.*prompt"):
            builtin_provider.read_json(ContentType.PROMPT, "gpt_prompt")

    def test_read_json_on_skill_raises_type_error(
        self, builtin_provider: PredefinedContentProvider
    ):
        with pytest.raises(TypeError, match="read_json.*not supported.*skills"):
            builtin_provider.read_json(ContentType.SKILL, "tool-call-file-parameter-formatting")

    def test_missing_name_raises_key_error(self, builtin_provider: PredefinedContentProvider):
        with pytest.raises(KeyError, match="not found"):
            builtin_provider.read_json(ContentType.TOOL, "nonexistent_tool")


class TestExtraLayers:
    """Tests for extra layer override/extension behavior."""

    def test_extra_layer_adds_new_content(self, tmp_path: Path):
        # Create extra layer with a new prompt
        prompt_dir = tmp_path / "prompt"
        prompt_dir.mkdir()
        (prompt_dir / "custom_prompt.md").write_text("Custom prompt content")

        settings = PredefinedSettings(extra_paths=[str(tmp_path)])
        provider = PredefinedContentProvider(settings)

        names = provider.list_names(ContentType.PROMPT)
        assert "custom_prompt" in names
        # Built-in prompts still present
        assert "gpt_prompt" in names

        content = provider.read_text(ContentType.PROMPT, "custom_prompt")
        assert content == "Custom prompt content"

    def test_extra_layer_overrides_builtin(self, tmp_path: Path):
        # Create extra layer overriding gpt_prompt
        prompt_dir = tmp_path / "prompt"
        prompt_dir.mkdir()
        (prompt_dir / "gpt_prompt.md").write_text("Overridden GPT prompt")

        settings = PredefinedSettings(extra_paths=[str(tmp_path)])
        provider = PredefinedContentProvider(settings)

        content = provider.read_text(ContentType.PROMPT, "gpt_prompt")
        assert content == "Overridden GPT prompt"

    def test_multiple_extra_layers_last_wins(self, tmp_path: Path):
        # Create two extra layers
        layer1 = tmp_path / "layer1"
        layer2 = tmp_path / "layer2"
        for layer in (layer1, layer2):
            prompt_dir = layer / "prompt"
            prompt_dir.mkdir(parents=True)

        (layer1 / "prompt" / "gpt_prompt.md").write_text("Layer1 GPT")
        (layer2 / "prompt" / "gpt_prompt.md").write_text("Layer2 GPT")

        settings = PredefinedSettings(extra_paths=[str(layer1), str(layer2)])
        provider = PredefinedContentProvider(settings)

        content = provider.read_text(ContentType.PROMPT, "gpt_prompt")
        assert content == "Layer2 GPT"

    def test_missing_extra_path_raises_runtime_error(self):
        settings = PredefinedSettings(extra_paths=["/nonexistent/path"])
        with pytest.raises(RuntimeError, match="not a directory"):
            PredefinedContentProvider(settings)

    def test_malformed_json_raises_runtime_error(self, tmp_path: Path):
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        (tool_dir / "bad_tool.json").write_text("{invalid json")

        settings = PredefinedSettings(extra_paths=[str(tmp_path)])
        with pytest.raises(RuntimeError, match="Failed to read"):
            PredefinedContentProvider(settings)

    def test_extra_layer_adds_directory_based_skill(self, tmp_path: Path):
        skill_dir = tmp_path / "skills" / "my-custom-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-custom-skill\ndescription: A custom skill\n---\nContent"
        )

        settings = PredefinedSettings(extra_paths=[str(tmp_path)])
        provider = PredefinedContentProvider(settings)

        names = provider.list_names(ContentType.SKILL)
        assert "my-custom-skill" in names
        content = provider.read_text(ContentType.SKILL, "my-custom-skill")
        assert "A custom skill" in content

    def test_flat_md_files_in_skills_dir_are_ignored(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "flat_skill.md").write_text("---\nname: flat\n---\nFlat content")

        settings = PredefinedSettings(extra_paths=[str(tmp_path)])
        provider = PredefinedContentProvider(settings)

        names = provider.list_names(ContentType.SKILL)
        assert "flat_skill" not in names
        assert "flat" not in names

    def test_extra_layer_overrides_builtin_skill(self, tmp_path: Path):
        skill_dir = tmp_path / "skills" / "tool-call-file-parameter-formatting"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("Overridden skill content")

        settings = PredefinedSettings(extra_paths=[str(tmp_path)])
        provider = PredefinedContentProvider(settings)

        content = provider.read_text(
            ContentType.SKILL, "tool-call-file-parameter-formatting"
        )
        assert content == "Overridden skill content"


class TestLayersInfo:
    """Tests for get_layers_info()."""

    def test_builtin_only_returns_single_layer(
        self, builtin_provider: PredefinedContentProvider
    ):
        layers = builtin_provider.get_layers_info()
        assert len(layers) == 1
        assert ContentType.PROMPT in layers[0].content_counts
        assert ContentType.TOOL in layers[0].content_counts
        assert ContentType.TOOLSET in layers[0].content_counts
        assert ContentType.SKILL in layers[0].content_counts

    def test_extra_layer_shows_overrides(self, tmp_path: Path):
        prompt_dir = tmp_path / "prompt"
        prompt_dir.mkdir()
        (prompt_dir / "gpt_prompt.md").write_text("Override")

        settings = PredefinedSettings(extra_paths=[str(tmp_path)])
        provider = PredefinedContentProvider(settings)

        layers = provider.get_layers_info()
        assert len(layers) == 2
        extra_layer = layers[1]
        assert extra_layer.content_counts.get(ContentType.PROMPT, 0) == 1
        assert "gpt_prompt" in extra_layer.overrides.get(ContentType.PROMPT, [])


class TestDeprecatedBasePath:
    """Tests for deprecated base_path handling."""

    def test_base_path_treated_as_extra_layer(self, tmp_path: Path):
        prompt_dir = tmp_path / "prompt"
        prompt_dir.mkdir()
        (prompt_dir / "custom_via_base.md").write_text("Via base_path")

        with pytest.warns(DeprecationWarning, match="PREDEFINED_BASE_PATH is deprecated"):
            settings = PredefinedSettings(base_path=str(tmp_path))
            provider = PredefinedContentProvider(settings)

        names = provider.list_names(ContentType.PROMPT)
        assert "custom_via_base" in names
        # Built-in still present
        assert "gpt_prompt" in names


class TestContentType:
    """Tests for ContentType enum properties."""

    def test_file_glob_text_types(self):
        assert ContentType.PROMPT.file_glob == "*.md"
        assert ContentType.SKILL.file_glob == "*.md"

    def test_file_glob_json_types(self):
        assert ContentType.TOOL.file_glob == "*.json"
        assert ContentType.TOOLSET.file_glob == "*.json"

    def test_is_text(self):
        assert ContentType.PROMPT.is_text is True
        assert ContentType.SKILL.is_text is True
        assert ContentType.TOOL.is_text is False
        assert ContentType.TOOLSET.is_text is False
