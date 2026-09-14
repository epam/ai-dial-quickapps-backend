"""``_InvokedSkillsContext`` — an ordinary ``SkillsProvider`` holding the picks."""

from quickapp.dial_prompt_skills import _DialPromptSkillsContext
from quickapp.dial_skills import _DialSkillsContext
from quickapp.skill_invocation._invoked_skills_context import _InvokedSkillsContext
from quickapp.skills.agent_skills_provider import AgentSkillsProvider
from tests.unit_tests.common.common import make_resolved_skill as _skill


class TestOrdering:

    def test_a_pick_wins_over_every_agent_source(self):
        assert _InvokedSkillsContext.order < AgentSkillsProvider.order
        assert _InvokedSkillsContext.order < _DialPromptSkillsContext.order
        assert _InvokedSkillsContext.order < _DialSkillsContext.order

    def test_display_name_is_human_readable(self):
        assert _InvokedSkillsContext.display_name == "user skills"


class TestResolvedSkills:

    def test_starts_empty(self):
        assert _InvokedSkillsContext().resolved_skills == []
        assert _InvokedSkillsContext().current_turn_urls == []

    def test_content_is_prefixed_with_a_user_selected_header(self):
        context = _InvokedSkillsContext()
        context.set_resolved_skills(
            [_skill("skills/b/sql-style", "sql-style", content="---\nbody")]
        )

        entry = context.resolved_skills[0]
        assert entry.content == (
            "Skill `sql-style`, selected by the user for this conversation.\n---\nbody"
        )

    def test_everything_else_is_kept_as_resolved(self):
        skill = _skill("skills/b/sql-style", "sql-style", files=("a.md",))
        context = _InvokedSkillsContext()
        context.set_resolved_skills([skill])

        entry = context.resolved_skills[0]
        assert (entry.url, entry.metadata, entry.files) == (skill.url, skill.metadata, skill.files)

    def test_find_skill_looks_up_by_url(self):
        context = _InvokedSkillsContext()
        context.set_resolved_skills([_skill("skills/b/sql-style", "sql-style")])

        assert context.find_skill("skills/b/sql-style") is not None
        assert context.find_skill("skills/b/other") is None
