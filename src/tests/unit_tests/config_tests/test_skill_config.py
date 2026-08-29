import logging

from pydantic import BaseModel

from quickapp.common.base_config import is_preview_model
from quickapp.config.application import nullify_preview_fields
from quickapp.config.skill import (
    DialPromptSkillConfig,
    DialSkillConfig,
    SkillConfig,
    enumerate_skill_configs,
)


class TestEnumerateSkillConfigs:
    """Positions are assigned before the list is split by type, so both
    initializers agree on what "first configured" means."""

    def test_keeps_positions_from_the_whole_skills_list(self):
        configs = [
            DialPromptSkillConfig(url="prompts/b/p1"),
            DialSkillConfig(url="skills/b/s1"),
            DialPromptSkillConfig(url="prompts/b/p2"),
        ]

        assert [i for i, _ in enumerate_skill_configs(configs, DialSkillConfig)] == [1]
        assert [i for i, _ in enumerate_skill_configs(configs, DialPromptSkillConfig)] == [0, 2]

    def test_none_is_an_empty_configuration(self):
        assert enumerate_skill_configs(None, DialSkillConfig) == []


class TestDiscriminatedUnion:
    def test_both_variants_parse_by_their_type_tag(self):
        class Cfg(BaseModel):
            skills: list[SkillConfig]

        parsed = Cfg.model_validate(
            {
                "skills": [
                    {"type": "dial-skill", "url": "skills/b/s"},
                    {"type": "dial-prompt", "url": "prompts/b/p"},
                ]
            }
        )

        assert isinstance(parsed.skills[0], DialSkillConfig)
        assert isinstance(parsed.skills[1], DialPromptSkillConfig)


class TestPreviewGating:
    def test_dial_skill_is_a_preview_model(self):
        assert is_preview_model(DialSkillConfig) is True

    def test_dial_prompt_is_not_gated(self):
        assert is_preview_model(DialPromptSkillConfig) is False

    def test_dial_skill_entries_are_dropped_when_preview_is_off(self, caplog):
        class Cfg(BaseModel):
            skills: list[SkillConfig]

        model = Cfg.model_construct(
            skills=[
                DialSkillConfig(url="skills/b/s"),
                DialPromptSkillConfig(url="prompts/b/p"),
            ]
        )

        with caplog.at_level(logging.WARNING):
            nullify_preview_fields(model)

        assert len(model.skills) == 1
        assert isinstance(model.skills[0], DialPromptSkillConfig)
        assert any("preview features are disabled" in r.message for r in caplog.records)


class TestDeprecation:

    def test_validating_a_dial_prompt_entry_emits_no_python_warning(self, recwarn):
        """The diagnostic channel is the initialization-issues stage, not
        `warnings` — a DeprecationWarning here would fire on every request."""
        DialPromptSkillConfig.model_validate({"type": "dial-prompt", "url": "prompts/b/p"})

        assert [w for w in recwarn if issubclass(w.category, DeprecationWarning)] == []
