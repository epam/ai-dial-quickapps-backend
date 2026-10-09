from unittest.mock import MagicMock

import openai

from quickapp.common.exception_message_resolver import resolve_exception
from quickapp.common.exceptions import ToolTimeoutError
from quickapp.dial_deployment_tooling._deployment_tool_error_exception import (
    DeploymentToolErrorException,
)
from quickapp.dial_deployment_tooling.deployment_stage_wrapper import DeploymentStageWrapper
from tests.unit_tests.common.common import make_openai_status_error


def _make_wrapper() -> DeploymentStageWrapper:
    return DeploymentStageWrapper(stage=MagicMock(), tool_config=None, stage_name="deployment")


def test_static_tools_are_not_rendered_in_the_stage():
    """Tools come from the app config, not the model, and their JSON would flood the stage."""
    wrapper = _make_wrapper()

    rendered = wrapper._get_formatted_parameters(
        {
            "query": "who won?",
            "tools": [{"type": "static_function", "static_function": {"name": "web_search"}}],
        }
    )

    assert "who won?" in rendered
    assert "web_search" not in rendered


def test_reasoning_effort_stays_visible():
    wrapper = _make_wrapper()

    rendered = wrapper._get_formatted_parameters({"query": "think", "reasoning_effort": "high"})

    assert "high" in rendered


def test_deployment_tool_error_renders_resolved_cause_and_status():
    wrapper = _make_wrapper()
    error = DeploymentToolErrorException(
        "image_generation_tool",
        resolve_exception(make_openai_status_error(openai.RateLimitError, 429)),
    )

    rendered = wrapper._build_debug_info_from_exception(error)

    assert rendered == (
        "> #### Error:\n"
        "Deployment tool 'image_generation_tool' returned an error: The request was "
        "rate-limited by the AI model service. Please try again later. (status code: 429)\n"
    )


def test_unexpected_exception_renders_curated_text_not_raw_string():
    wrapper = _make_wrapper()

    rendered = wrapper._build_debug_info_from_exception(ValueError("internal detail"))

    assert rendered == (
        "> #### Error:\n"
        "Something went wrong with the execution of your request. "
        "Please contact your administrator.\n"
    )


def test_tool_timeout_renders_its_cause():
    wrapper = _make_wrapper()

    rendered = wrapper._build_debug_info_from_exception(ToolTimeoutError("image", 30))

    assert rendered == (
        "> #### Error:\nTool call 'image' timed out after 30 seconds. Please try again later.\n"
    )
