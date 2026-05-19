from unittest.mock import MagicMock

import pytest
from aidial_sdk.chat_completion import Stage

from quickapp.common import ToolCallResult

# noinspection PyProtectedMember
from quickapp.skills._skill_reader_stage_wrapper import _SkillReaderStageWrapper


@pytest.fixture
def mock_stage():
    stage = MagicMock(spec=Stage)
    stage.__enter__.return_value = stage
    return stage


@pytest.fixture
def wrapper(mock_stage):
    return _SkillReaderStageWrapper(
        stage=mock_stage,
        tool_config=None,
        stage_name="Reading Skill: ",
    )


def test_build_debug_info_from_result_wraps_content_in_code_fence(wrapper):
    skill_content = "# Heading\n## Subheading\nbody text"
    result = ToolCallResult(content=skill_content, content_type="text/markdown")

    output = wrapper._build_debug_info_from_result(result)

    assert output == f"Skill Content:\n```\n{skill_content}\n```\n"


def test_build_debug_info_from_exception_wraps_message_in_code_fence(wrapper):
    exception = ValueError("skill not found")

    output = wrapper._build_debug_info_from_exception(exception)

    assert output == "Error:\n```\nskill not found\n```\n"
