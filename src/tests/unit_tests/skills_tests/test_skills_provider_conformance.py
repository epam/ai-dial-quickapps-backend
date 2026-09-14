"""Conformance tests: ``_DialPromptSkillsContext`` and ``_DialSkillsContext``
each implement ``SkillsProvider`` directly. (``AgentSkillsProvider``'s is
covered in ``test_agent_skills_provider.py``.)"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.dial_prompt_skills import _DialPromptSkillsContext
from quickapp.dial_skills import DialSkillReader, _DialSkillsContext
from quickapp.skills.agent_skills_provider import AgentSkillsProvider
from tests.unit_tests.common.common import make_resolved_skill as _skill


class TestOrdering:

    def test_precedence_is_predefined_then_prompt_then_dial_skill(self):
        assert AgentSkillsProvider.order < _DialPromptSkillsContext.order < _DialSkillsContext.order

    def test_display_names_are_human_readable(self):
        assert AgentSkillsProvider.display_name == "predefined skills"
        assert _DialPromptSkillsContext.display_name == "DIAL prompt skills"
        assert _DialSkillsContext.display_name == "DIAL skill resources"


class TestDialPromptSkillsContext:

    def test_resolved_skills_starts_empty_and_accumulates(self):
        context = _DialPromptSkillsContext()
        assert context.resolved_skills == []

        skill = _skill("prompts/b/p", "p", content="body")
        context.extend_resolved_skills([skill])

        assert context.resolved_skills == [skill]

    @pytest.mark.asyncio
    async def test_prompt_skills_have_no_reader(self):
        context = _DialPromptSkillsContext()
        context.extend_resolved_skills([_skill("prompts/b/p", "p")])

        assert context.resolved_skills[0].reader is None


class TestDialSkillsContext:

    def test_resolved_skills_starts_empty_and_accumulates(self):
        context = _DialSkillsContext()
        assert context.resolved_skills == []

        skill = _skill("skills/b/s", "s", files=("a.md",))
        context.extend_resolved_skills([skill])

        assert context.resolved_skills == [skill]

    @pytest.mark.asyncio
    async def test_read_file_delegates_to_the_skills_own_reader(self):
        reader = MagicMock(spec=DialSkillReader)
        reader.read_bundled_file = AsyncMock(return_value="file content")
        skill = _skill("skills/b/s", "s", files=("a.md",), reader=reader)
        context = _DialSkillsContext()
        context.extend_resolved_skills([skill])

        result = await context.resolved_skills[0].read_file("a.md")

        assert result == "file content"
        reader.read_bundled_file.assert_awaited_once_with(skill, "a.md")
