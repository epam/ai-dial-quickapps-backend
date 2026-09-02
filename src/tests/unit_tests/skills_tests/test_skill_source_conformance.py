"""Conformance tests for the three ``SkillSource`` adapters.

Each adapter is a thin translation layer between an existing focused class
(``AgentSkillsProvider``, ``_DialPromptSkillsContext``, ``_DialSkillsContext``
+ ``DialSkillReader``) and the ``SkillSource`` shape ``SkillsRegistry``
consumes. These tests pin that translation, independent of
``SkillsRegistry``'s own merge logic (covered in
``test_skills_registry_dial_skills.py``).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.exceptions import SkillInitializationException
from quickapp.dial_prompt_skills import _DialPromptSkillsContext
from quickapp.dial_prompt_skills._dial_prompt_skills_source import _DialPromptSkillsSource
from quickapp.dial_skills import DialSkillReader, _DialSkillsContext
from quickapp.dial_skills._dial_skills_source import _DialSkillsSource
from quickapp.skills._predefined_skills_source import _PredefinedSkillsSource
from quickapp.skills._skill_metadata import SkillMetadata
from quickapp.skills.agent_skills_provider import AgentSkillsProvider
from tests.unit_tests.common.common import make_resolved_dial_prompt_skill as _prompt_skill
from tests.unit_tests.common.common import make_resolved_dial_skill as _dial_skill


class TestPredefinedSkillsSource:

    def test_order_is_lowest(self):
        assert _PredefinedSkillsSource.order == 0

    def test_display_name_is_human_readable(self):
        assert _PredefinedSkillsSource.display_name == "predefined skills"

    def test_get_candidates_maps_metadata_and_content_with_no_read_file(self):
        provider = MagicMock(spec=AgentSkillsProvider)
        metadata = SkillMetadata(name="refunds", description="d")
        provider.get_all_skills.return_value = [metadata]
        provider.get_all_skill_contents.return_value = {"refunds": "body"}
        source = _PredefinedSkillsSource(provider)

        candidates = source.get_candidates()

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.metadata is metadata
        assert candidate.content == "body"
        assert candidate.read_file is None

    def test_report_exceptions_no_ops(self):
        source = _PredefinedSkillsSource(MagicMock(spec=AgentSkillsProvider))

        source.report_exceptions([SkillInitializationException(url="x", reason="unreachable")])


class TestDialPromptSkillsSource:

    def test_order_is_between_predefined_and_dial_skill(self):
        assert _PredefinedSkillsSource.order < _DialPromptSkillsSource.order
        assert _DialPromptSkillsSource.order < _DialSkillsSource.order

    def test_display_name_is_human_readable(self):
        assert _DialPromptSkillsSource.display_name == "DIAL prompt skills"

    def test_get_candidates_maps_from_context_with_no_read_file(self):
        context = _DialPromptSkillsContext()
        context.extend_resolved_skills([_prompt_skill("prompts/b/p", "p", content="body")])
        source = _DialPromptSkillsSource(context)

        candidates = source.get_candidates()

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.url == "prompts/b/p"
        assert candidate.metadata.name == "p"
        assert candidate.content == "body"
        assert candidate.read_file is None

    def test_report_exceptions_forwards_to_context(self):
        context = _DialPromptSkillsContext()
        source = _DialPromptSkillsSource(context)
        exc = SkillInitializationException(url="x", reason="collided")

        source.report_exceptions([exc])

        assert context.exceptions == [exc]


class TestDialSkillsSource:

    def test_order_is_highest(self):
        assert _DialSkillsSource.order == 20

    def test_display_name_is_human_readable(self):
        assert _DialSkillsSource.display_name == "DIAL skill resources"

    def test_get_candidates_maps_from_context(self):
        skill = _dial_skill("skills/b/s", "s", content="body", files=("a.md",))
        context = _DialSkillsContext()
        context.extend_resolved_skills([skill])
        source = _DialSkillsSource(context, MagicMock(spec=DialSkillReader))

        candidates = source.get_candidates()

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.url == "skills/b/s"
        assert candidate.metadata.name == "s"
        assert candidate.content == "body"
        assert candidate.read_file is not None

    @pytest.mark.asyncio
    async def test_candidate_read_file_calls_reader_with_the_right_skill(self):
        skill = _dial_skill("skills/b/s", "s", files=("a.md",))
        context = _DialSkillsContext()
        context.extend_resolved_skills([skill])
        reader = MagicMock(spec=DialSkillReader)
        reader.read_bundled_file = AsyncMock(return_value="file content")
        source = _DialSkillsSource(context, reader)

        candidate = source.get_candidates()[0]
        result = await candidate.read_file("a.md")

        assert result == "file content"
        reader.read_bundled_file.assert_awaited_once_with(skill, "a.md")

    def test_report_exceptions_forwards_to_context(self):
        context = _DialSkillsContext()
        source = _DialSkillsSource(context, MagicMock(spec=DialSkillReader))
        exc = SkillInitializationException(url="x", reason="collided")

        source.report_exceptions([exc])

        assert context.exceptions == [exc]
