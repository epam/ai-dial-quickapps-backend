import re
from unittest.mock import MagicMock

import pytest

from quickapp.task_tooling._exceptions import TaskToolErrorException
from quickapp.task_tooling._task_stage_wrapper import _TaskStageWrapper
from quickapp.task_tooling._tool_config import RUN_TASK_TOOL_CONFIG


def _wrapper() -> tuple[_TaskStageWrapper, MagicMock]:
    stage = MagicMock()
    return _TaskStageWrapper(stage=stage, tool_config=RUN_TASK_TOOL_CONFIG), stage


def _names(stage: MagicMock) -> str:
    return "".join(call.args[0] for call in stage.append_name.call_args_list)


def _content(stage: MagicMock) -> str:
    return "".join(call.args[0] for call in stage.append_content.call_args_list)


def test_stage_title_carries_the_task_label():
    wrapper, stage = _wrapper()
    with wrapper:
        wrapper.add_parameters({"name": "Compare vendor pricing", "prompt": "p", "tools": []})

    # The timed stage appends its duration on exit.
    assert re.fullmatch(r"Task: Compare vendor pricing \[[\d.]+s\]", _names(stage))


@pytest.mark.parametrize(
    "tools, rendered",
    [
        (["inherit"], "inherit"),
        ("inherit", "inherit"),
        (["web_search", "internal_file_list"], "web_search, internal_file_list"),
        ([], "none"),
    ],
)
def test_header_shows_prompt_and_tools(tools, rendered):
    wrapper, stage = _wrapper()
    wrapper.add_parameters({"name": "n", "prompt": "Find the **cheapest** one.", "tools": tools})

    content = _content(stage)
    assert "Find the **cheapest** one." in content
    assert f"**Tools:** {rendered}" in content


def test_tool_error_renders_its_user_facing_message():
    wrapper, stage = _wrapper()
    error = TaskToolErrorException("ran out of time")

    wrapper.add_exception(error, "ref123")

    content = _content(stage)
    assert "ran out of time" in content
    assert "ref123" in content
