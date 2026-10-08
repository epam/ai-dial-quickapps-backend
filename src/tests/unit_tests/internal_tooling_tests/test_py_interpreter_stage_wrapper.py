from unittest.mock import MagicMock

from quickapp.common.exceptions import HiddenToolErrorException, ToolTimeoutError
from quickapp.common.url_classification import unsupported_scheme_error
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_stage_wrapper import (
    _PyInterpreterStageWrapper,
)


def _make_wrapper() -> _PyInterpreterStageWrapper:
    return _PyInterpreterStageWrapper(stage=MagicMock(), tool_config=None, stage_name="python")


def test_exception_is_not_described_as_a_dial_deployment_call():
    wrapper = _make_wrapper()

    rendered = wrapper._build_debug_info_from_exception(ValueError("internal detail"))

    assert rendered == (
        "> #### Error:\n"
        "Something went wrong with the execution of your request. "
        "Please contact your administrator.\n"
    )


def test_tool_timeout_renders_its_cause():
    wrapper = _make_wrapper()

    rendered = wrapper._build_debug_info_from_exception(ToolTimeoutError("python", 30))

    assert rendered == (
        "> #### Error:\nTool call 'python' timed out after 30 seconds. Please try again later.\n"
    )


def test_hidden_error_renders_placeholder_as_is():
    wrapper = _make_wrapper()

    rendered = wrapper._build_debug_info_from_exception(HiddenToolErrorException())

    assert rendered == "> #### Error:\nAn error occurred while executing the tool.\n"


def test_invalid_parameter_renders_its_own_text():
    """The agent retries these itself, so the stage must not send the user to an administrator."""
    wrapper = _make_wrapper()
    error = unsupported_scheme_error("ftp://host/file.pdf", parameter_name="attachment_urls")

    rendered = wrapper._build_debug_info_from_exception(error)

    assert rendered == f"> #### Error:\n{error.message}\n"
    assert "administrator" not in rendered
