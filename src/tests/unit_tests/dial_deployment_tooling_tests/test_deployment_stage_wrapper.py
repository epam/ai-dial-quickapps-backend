from unittest.mock import MagicMock

import httpx
import openai

from quickapp.dial_deployment_tooling.deployment_stage_wrapper import DeploymentStageWrapper


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

    assert "rate-limited" in rendered
    assert "429" in rendered
    assert "General exception" not in rendered


def test_mid_stream_rate_limit_shows_cause_and_status_code():
    # A 429 after streaming started is a plain APIError with the status only in `code`.
    request = httpx.Request("POST", "http://dial-core/openai/deployments/app/chat/completions")
    error = openai.APIError("raw error detail", request=request, body={"code": "429"})

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert "rate-limited" in rendered
    assert "429" in rendered
    assert "General exception" not in rendered


def test_non_rate_limit_openai_error_keeps_generic_text():
    request = httpx.Request("POST", "http://dial-core/openai/deployments/image/chat/completions")
    error = openai.InternalServerError(
        "raw error detail", response=httpx.Response(500, request=request), body=None
    )

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert "General exception" in rendered
    assert "rate-limited" not in rendered


def test_rate_limit_prefers_upstream_display_message():
    error = _make_rate_limit_error({"error": {"display_message": "Daily limit 3000 exceeded"}})

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert "Daily limit 3000 exceeded" in rendered
    assert "rate-limited" not in rendered


def test_rate_limit_blank_display_message_falls_back_to_canned_text():
    error = _make_rate_limit_error({"error": {"display_message": "   "}})

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert "rate-limited" in rendered


def test_unknown_exception_keeps_generic_text():
    rendered = _make_wrapper()._build_debug_info_from_exception(RuntimeError("boom"))

    assert "General exception" in rendered


def test_error_reference_is_appended_to_stage_content():
    wrapper = _make_wrapper()

    wrapper.add_exception(RuntimeError("boom"), "ab12cd34")

    rendered = wrapper.stage.append_content.call_args.args[0]
    assert "Error reference" in rendered
    assert "ab12cd34" in rendered
