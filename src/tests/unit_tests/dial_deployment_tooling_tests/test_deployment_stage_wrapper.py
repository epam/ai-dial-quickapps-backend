from unittest.mock import MagicMock

import httpx
import openai
import pytest

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


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, "The tool could not process the request."),
        (404, "The tool could not process the request."),
        (500, "The tool encountered an internal error."),
        (503, "The tool encountered an internal error."),
    ],
)
def test_upstream_status_shows_tool_message_and_status_code(status: int, expected: str):
    request = httpx.Request("POST", "http://dial-core/openai/deployments/image/chat/completions")
    error = openai.APIStatusError(
        "raw error detail", response=httpx.Response(status, request=request), body=None
    )

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert rendered == f"> #### Error:\n{expected}\n> #### Status Code:\n{status}\n"


def test_display_message_wins_for_any_status():
    request = httpx.Request("POST", "http://dial-core/openai/deployments/app/chat/completions")
    error = openai.BadRequestError(
        "raw error detail",
        response=httpx.Response(400, request=request),
        body={"error": {"display_message": "The document is too large"}},
    )

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert rendered == "> #### Error:\nThe document is too large\n> #### Status Code:\n400\n"


def test_display_message_without_status_omits_status_code():
    request = httpx.Request("POST", "http://dial-core/openai/deployments/app/chat/completions")
    error = openai.APIError(
        "raw error detail",
        request=request,
        body={"code": "document_too_large", "display_message": "The document is too large"},
    )

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert rendered == "> #### Error:\nThe document is too large\n"


def test_document_processing_failure_shows_status_without_internal_detail():
    request = httpx.Request("POST", "http://dial-core/openai/deployments/dial-rag/chat/completions")
    internal_message = (
        "Error on processing document: [Errno 2] No such file or directory: "
        "'/tmp/tmpabc123/doc_file.pdf'"
    )
    error = openai.APIError(
        internal_message,
        request=request,
        body={"message": internal_message, "type": "runtime_error", "code": "500"},
    )

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert rendered == (
        "> #### Error:\nThe tool encountered an internal error.\n> #### Status Code:\n500\n"
    )


def test_blank_display_message_falls_back_to_status_message():
    request = httpx.Request("POST", "http://dial-core/openai/deployments/app/chat/completions")
    error = openai.BadRequestError(
        "raw error detail",
        response=httpx.Response(400, request=request),
        body={"error": {"display_message": "   "}},
    )

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert rendered == (
        "> #### Error:\nThe tool could not process the request.\n> #### Status Code:\n400\n"
    )


def test_non_error_status_keeps_generic_text():
    request = httpx.Request("POST", "http://dial-core/openai/deployments/app/chat/completions")
    error = openai.APIError("raw error detail", request=request, body={"code": "200"})

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert "General exception" in rendered


def test_openai_error_without_status_keeps_generic_text():
    request = httpx.Request("POST", "http://dial-core/openai/deployments/app/chat/completions")
    error = openai.APIError("raw error detail", request=request, body=None)

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert "General exception" in rendered
    assert "raw error detail" not in rendered


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


def test_rate_limit_display_message_is_capped():
    error = _make_rate_limit_error({"error": {"display_message": "x" * 600}})

    rendered = _make_wrapper()._build_debug_info_from_exception(error)

    assert "x" * 499 + "…" in rendered
    assert "x" * 500 not in rendered
