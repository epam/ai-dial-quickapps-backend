"""``SkillInvocationSettings`` — the per-message cap can never exceed the total one."""

from quickapp.skills.invocation._settings import SkillInvocationSettings


class TestClampPerMessageToTotal:

    def test_per_message_cap_left_alone_when_within_the_total(self):
        settings = SkillInvocationSettings(
            SKILL_INVOCATION_MAX_SKILLS=10, SKILL_INVOCATION_MAX_SKILLS_PER_MESSAGE=5
        )

        assert settings.max_skills_per_message == 5

    def test_per_message_cap_is_clamped_down_to_the_total(self):
        settings = SkillInvocationSettings(
            SKILL_INVOCATION_MAX_SKILLS=3, SKILL_INVOCATION_MAX_SKILLS_PER_MESSAGE=5
        )

        assert settings.max_skills_per_message == 3

    def test_equal_caps_are_left_unchanged(self):
        settings = SkillInvocationSettings(
            SKILL_INVOCATION_MAX_SKILLS=4, SKILL_INVOCATION_MAX_SKILLS_PER_MESSAGE=4
        )

        assert settings.max_skills_per_message == 4
