from unittest.mock import MagicMock

import pytest
from aidial_sdk.chat_completion import Stage

# noinspection PyProtectedMember
from quickapp.dial_files_tooling._stage_wrapper import _FileStageWrapper
from quickapp.dial_files_tooling._tool_configs import EDIT_FILE_TOOL_CONFIG, WRITE_FILE_TOOL_CONFIG


@pytest.fixture
def mock_stage():
    stage = MagicMock(spec=Stage)
    stage.__enter__.return_value = stage
    stage.append_content = MagicMock()
    stage.append_name = MagicMock()
    return stage


def _write_wrapper(mock_stage) -> _FileStageWrapper:
    return _FileStageWrapper(
        stage=mock_stage, tool_config=WRITE_FILE_TOOL_CONFIG, stage_name="Write file"
    )


def _edit_wrapper(mock_stage) -> _FileStageWrapper:
    return _FileStageWrapper(
        stage=mock_stage, tool_config=EDIT_FILE_TOOL_CONFIG, stage_name="Edit file"
    )


def test_content_wrapped_in_code_block(mock_stage):
    wrapper = _write_wrapper(mock_stage)

    rendered = wrapper._get_formatted_parameters(
        {"path": "report.md", "content": "# Heading\n\nSome **bold** text."}
    )

    # The markdown content appears verbatim inside a fenced code block, so the
    # heading/bold markup is not rendered by the UI.
    assert "```\n# Heading\n\nSome **bold** text.\n```" in rendered


def test_fence_grows_for_embedded_code_block(mock_stage):
    wrapper = _write_wrapper(mock_stage)

    content = "Intro\n\n```python\nprint('hi')\n```\n\nOutro"
    rendered = wrapper._get_formatted_parameters({"path": "report.md", "content": content})

    # The inner fence is 3 backticks, so the wrapper must open with 4 to avoid
    # closing early. The whole content (including the inner fence) stays intact.
    assert "````\n" + content + "\n````" in rendered
    assert "```python" in rendered


def test_long_param_rendered_last(mock_stage):
    wrapper = _write_wrapper(mock_stage)

    # Input lists the long `content` before the short `path`.
    rendered = wrapper._get_formatted_parameters(
        {"content": "body", "path": "report.md", "content_type": "text/markdown"}
    )

    # Short params (path, content_type) come before the long content block.
    assert rendered.index("path:") < rendered.index("content:")
    assert rendered.index("content_type:") < rendered.index("content:")


def test_edit_strings_wrapped_in_code_blocks(mock_stage):
    wrapper = _edit_wrapper(mock_stage)

    rendered = wrapper._get_formatted_parameters(
        {"path": "a.md", "old_string": "**old**", "new_string": "**new**"}
    )

    assert "```\n**old**\n```" in rendered
    assert "```\n**new**\n```" in rendered
    # path is short and rendered before the long replacement strings.
    assert rendered.index("path:") < rendered.index("old_string:")
