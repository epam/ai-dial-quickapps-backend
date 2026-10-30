import pytest

from quickapp.common.tool_names import (
    INTERNAL_FILE_READ_LINES_TOOL_NAME,
    INTERNAL_FILE_SEARCH_TOOL_NAME,
)
from tests.integration_tests.test_runner.config import SimilarityThreshold, TestConfig
from tests.integration_tests.test_runner.e2e_runner import e2e_test
from tests.integration_tests.test_runner.models import ToolCall, TstCase
from tests.integration_tests.test_runner.stub_deployment import (
    NESTED_STUB_ANSWER,
    NESTED_STUB_DEPLOYMENT_ID,
    NESTED_STUB_MODELS,
    NESTED_STUB_TOOL_NAME,
    STUB_ANSWER,
    STUB_COMPLETION_TOKENS,
    STUB_DEPLOYMENT_ID,
    STUB_PROMPT_TOKENS,
    STUB_TOOL_NAME,
)

USAGE_ENV = {"SHOW_USAGE_STATISTICS": "true"}


# The stub deployments (served by the cache middleware) mimic OpenAI-compatible services:
# they report usage only when the caller sends `stream_options.include_usage`.
@pytest.mark.integration
@e2e_test(
    config_file_set="empty",
    no_cache=True,
    runs=1,
    env=USAGE_ENV,
    toolsets=[TestConfig.get_usage_stub_toolset()],
    test_case=TstCase(
        "deployment_tool_usage",
        "A deployment tool's usage reaches the Usage Statistics table next to the orchestrator's",
        similarity_threshold=SimilarityThreshold.LENIENT.value,
    ).add_user_message(
        user_message=f"Call the {STUB_TOOL_NAME} tool with the query 'ping' and repeat its reply verbatim.",
        tool_calls=[ToolCall(STUB_TOOL_NAME)],
        answer=[STUB_ANSWER],
        # "Orchestrator" proves the table is on; the tool's row carries its own tokens.
        usage_statistics_contains=[
            "Orchestrator",
            f"Tool: {STUB_TOOL_NAME} | {STUB_DEPLOYMENT_ID} | "
            f"{STUB_PROMPT_TOKENS} | {STUB_COMPLETION_TOKENS} |",
        ],
    ),
)
def test_deployment_tool_usage_is_reported(client):
    pass


@pytest.mark.integration
@e2e_test(
    config_file_set="empty",
    no_cache=True,
    runs=1,
    env=USAGE_ENV,
    toolsets=[TestConfig.get_usage_stub_toolset(NESTED_STUB_DEPLOYMENT_ID, NESTED_STUB_TOOL_NAME)],
    test_case=TstCase(
        "nested_app_usage_per_model",
        "A nested app's per-model usage becomes one row per model, without double counting its total",
        similarity_threshold=SimilarityThreshold.LENIENT.value,
    ).add_user_message(
        user_message=f"Call the {NESTED_STUB_TOOL_NAME} tool with the query 'ping' and repeat its reply verbatim.",
        tool_calls=[ToolCall(NESTED_STUB_TOOL_NAME)],
        answer=[NESTED_STUB_ANSWER],
        usage_statistics_contains=[
            "Orchestrator",
            *(
                f"Tool: {NESTED_STUB_TOOL_NAME} | {m.model} | {m.prompt_tokens} | {m.completion_tokens} |"
                for m in NESTED_STUB_MODELS
            ),
        ],
        # The app also reports a total under its own deployment id; the breakdown supersedes it.
        usage_statistics_not_contains=[f"| {NESTED_STUB_DEPLOYMENT_ID} |"],
    ),
)
def test_nested_app_usage_per_model_is_reported(client):
    pass


# A threshold below the stub's answer size makes every stub result an offloaded one.
OFFLOAD_USAGE_ENV = {**USAGE_ENV, "TOOL_CALL_RESULT_OFFLOAD__SIZE_THRESHOLD": "20"}


@pytest.mark.integration
@e2e_test(
    config_file_set="empty",
    no_cache=True,
    runs=1,
    env=OFFLOAD_USAGE_ENV,
    toolsets=[TestConfig.get_usage_stub_toolset()],
    test_case=TstCase(
        "offloaded_tool_result_usage",
        "An offloaded deployment-tool result keeps its usage in the Usage Statistics table",
        similarity_threshold=SimilarityThreshold.LENIENT.value,
    ).add_user_message(
        user_message=f"Call the {STUB_TOOL_NAME} tool with the query 'ping' and tell me whether it answered.",
        tool_calls=[
            ToolCall(STUB_TOOL_NAME).add_result_check(contains="was too large"),
            # The orchestrator may read the offloaded file back before answering.
            ToolCall(INTERNAL_FILE_READ_LINES_TOOL_NAME, min_calls=0, max_calls=3),
            ToolCall(INTERNAL_FILE_SEARCH_TOOL_NAME, min_calls=0, max_calls=3),
        ],
        usage_statistics_contains=[
            "Orchestrator",
            f"Tool: {STUB_TOOL_NAME} | {STUB_DEPLOYMENT_ID} | "
            f"{STUB_PROMPT_TOKENS} | {STUB_COMPLETION_TOKENS} |",
        ],
    ),
)
def test_offloaded_tool_result_usage_is_reported(client):
    pass
