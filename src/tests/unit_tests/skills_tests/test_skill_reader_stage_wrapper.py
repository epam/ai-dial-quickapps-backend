from unittest.mock import MagicMock

import pytest
from aidial_sdk.chat_completion import Stage

from quickapp.common import ToolCallResult

# noinspection PyProtectedMember
from quickapp.skills._skill_reader_stage_wrapper import _SkillReaderStageWrapper
from quickapp.skills._tool_configs import SKILL_READER_TOOL_CONFIG


@pytest.fixture
def mock_stage():
    stage = MagicMock(spec=Stage)
    stage.__enter__.return_value = stage
    return stage


@pytest.fixture
def wrapper(mock_stage):
    # The real config, not None: it is what marks `skill_name` as title-only, so
    # an empty config map would silently render every parameter via the fallback.
    return _SkillReaderStageWrapper(
        stage=mock_stage,
        tool_config=SKILL_READER_TOOL_CONFIG,
        stage_name="Reading Skill: ",
    )


class TestFormattedParameters:
    """`skill_name` goes in the stage title; only `file_path` is rendered as a
    parameter, so a manifest read shows no Request block at all."""

    def test_a_manifest_read_renders_nothing(self, wrapper):
        assert wrapper._get_formatted_parameters({"skill_name": "demo-skill"}) == ""
        assert wrapper._get_formatted_parameters({}) == ""

    def test_a_blank_file_path_renders_nothing(self, wrapper):
        params = {"skill_name": "demo-skill", "file_path": "  "}

        assert wrapper._get_formatted_parameters(params) == ""

    def test_a_file_read_shows_the_path_and_not_the_skill_name(self, wrapper):
        params = {"skill_name": "demo-skill", "file_path": "references/a.md"}

        output = wrapper._get_formatted_parameters(params)

        assert "references/a.md" in output
        assert "demo-skill" not in output


def test_build_debug_info_from_result_wraps_content_in_code_fence(wrapper):
    skill_content = "# Heading\n## Subheading\nbody text"
    result = ToolCallResult(content=skill_content, content_type="text/markdown")

    output = wrapper._build_debug_info_from_result(result)

    assert output == f"#### Skill Content:\n```\n{skill_content}\n```\n"


def test_build_debug_info_from_exception_wraps_message_in_code_fence(wrapper):
    exception = ValueError("skill not found")

    output = wrapper._build_debug_info_from_exception(exception)

    assert output == "#### Error:\n```\nskill not found\n```\n"


def test_build_debug_info_from_result_uses_longer_fence_for_nested_fences(wrapper):
    # A skill body that itself contains a ``` code fence must not break out of
    # the wrapping fence, otherwise the rendered stage in the UI is corrupted.
    skill_content = "intro\n```python\nprint('hi')\n```\noutro"
    result = ToolCallResult(content=skill_content, content_type="text/markdown")

    output = wrapper._build_debug_info_from_result(result)

    assert output == f"#### Skill Content:\n````\n{skill_content}\n````\n"
