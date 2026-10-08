from unittest.mock import MagicMock

import httpx
import openai
from aidial_client import DialException

from quickapp.common.exception_message_resolver import resolve_exception
from quickapp.common.exceptions import HiddenToolErrorException, ToolTimeoutError
from quickapp.common.url_classification import unsupported_scheme_error
from quickapp.dial_deployment_tooling._deployment_tool_error_exception import (
    DeploymentToolErrorException,
)
from quickapp.dial_deployment_tooling.deployment_stage_wrapper import DeploymentStageWrapper
from tests.unit_tests.common.common import make_openai_status_error


def _make_wrapper() -> DeploymentStageWrapper:
    return DeploymentStageWrapper(stage=MagicMock(), tool_config=None, stage_name="deployment")


def _make_rate_limit_error(body: object = None) -> openai.RateLimitError:
    request = httpx.Request("POST", "http://dial-core/openai/deployments/image/chat/completions")
    return openai.RateLimitError(
        "raw error detail", response=httpx.Response(429, request=request), body=body
    )


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


def test_rate_limit_shows_cause_and_status_code():
    rendered = _make_wrapper()._build_debug_info_from_exception(_make_rate_limit_error())

    assert rendered == (
        "> #### Error:\nThe request was rate-limited by the AI model service. "
        "Please try again later. (status code: 429)\n"
    )


def test_mid_stream_rate_limit_shows_cause_and_status_code():
    # A 429 after streaming started is a plain APIError with the status only in `code`.
    request = httpx.Request("POST", "http://dial-core/openai/deployments/app/chat/completions")
    error = openai.APIError("raw error detail", request=request, body={"code": "429"})

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert rendered == (
        "> #### Error:\nThe request was rate-limited by the AI model service. "
        "Please try again later. (status code: 429)\n"
    )


def test_internal_server_error_renders_cause_and_status():
    error = make_openai_status_error(openai.InternalServerError, 500)

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert rendered == (
        "> #### Error:\nThe AI model service encountered an internal error. "
        "Please try again later. (status code: 500)\n"
    )


def test_rate_limit_prefers_upstream_display_message():
    error = _make_rate_limit_error({"error": {"display_message": "Daily limit 3000 exceeded"}})

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert "Daily limit 3000 exceeded" in rendered
    assert "rate-limited" not in rendered


def test_rate_limit_blank_display_message_falls_back_to_canned_text():
    error = _make_rate_limit_error({"error": {"display_message": "   "}})

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert "rate-limited" in rendered


def test_error_reference_is_appended_to_stage_content():
    wrapper = _make_wrapper()

    wrapper.add_exception(RuntimeError("boom"), "ab12cd34")

    rendered = wrapper.stage.append_content.call_args.args[0]
    assert "Error reference" in rendered
    assert "ab12cd34" in rendered


def test_rate_limit_display_message_is_capped():
    error = _make_rate_limit_error({"error": {"display_message": "x" * 600}})

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert "x" * 499 + "…" in rendered
    assert "x" * 500 not in rendered


def test_deployment_tool_error_renders_resolved_cause_and_status():
    wrapper = _make_wrapper()
    error = DeploymentToolErrorException(
        "image_generation_tool",
        resolve_exception(make_openai_status_error(openai.RateLimitError, 429)),
        upstream_message="raw upstream body",
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


def test_attachment_dial_error_renders_service_wording_and_status():
    """A missing attachment fails the DIAL metadata lookup before the deployment is called."""
    wrapper = _make_wrapper()

    rendered = wrapper._build_debug_info_from_exception(
        DialException(message="raw error detail", status_code=404)
    )

    assert rendered == (
        "> #### Error:\n"
        "A required service or resource could not be found. "
        "Please contact your administrator. (status code: 404)\n"
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
