from typing import get_args

import pytest

from quickapp.common.tool_names import INTERNAL_FILE_TOOL_NAME_PREFIX
from quickapp.config.dial_files import DialFilesToolName
from quickapp.config.hooks import HookEvent, ToolCallHookConfig
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from tests.integration_tests.test_runner.config import SimilarityThreshold
from tests.integration_tests.test_runner.e2e_runner import e2e_test
from tests.integration_tests.test_runner.models import ToolCall, TstCase

# Asserts on the contract only (the tools sent to the LLM and the answer), never on MCP server internals.
# A model calling a hidden tool anyway is tolerated, but then it must have received the fallback reply.
TOOLSET_NAME = "hooks_test"
LOOKUP_STOCK = "lookup_stock"
LIST_WAREHOUSES = "list_warehouses"
MISSING_TOOL = "no_such_tool"

LOOKUP_STOCK_FUNCTION = f"{TOOLSET_NAME}_{LOOKUP_STOCK}"
LIST_WAREHOUSES_FUNCTION = f"{TOOLSET_NAME}_{LIST_WAREHOUSES}"

STOCK_QUESTION = "What is the current stock quantity of SKU-1? Reply with only the number."
WAREHOUSES_QUESTION = "Which warehouses exist? Reply with only their names."
WAREHOUSES_ANSWER = ["North, South, East", "North, South and East"]


def _toolset(allowed_tools: list[str], hidden_from_model: list[str] | None) -> MCPToolSet:
    return MCPToolSet(
        name=TOOLSET_NAME,
        description="Stock and warehouse lookups",
        mcp_server_info=MCPServerInfo(
            url="http://localhost:8003/mcp", protocol=MCPProtocol.streamable_http
        ),
        allowed_tools=allowed_tools,
        hidden_from_model=hidden_from_model,
    )


def _stock_hook(tool_name: str = LOOKUP_STOCK) -> ToolCallHookConfig:
    return ToolCallHookConfig(
        event=HookEvent.ON_REQUEST_START,
        toolset_name=TOOLSET_NAME,
        tool_name=tool_name,
        arguments={"sku": "SKU-1"},
    )


def _hidden_stock_call() -> ToolCall:
    # Optional: some models imitate the synthetic pair a hook leaves in history. When one does,
    # the platform's reply is what the model must have received.
    return ToolCall(LOOKUP_STOCK_FUNCTION, min_calls=0, max_calls=2).add_result_check(
        contains="not available"
    )


def _optional_call(name: str) -> ToolCall:
    return ToolCall(name, min_calls=0, max_calls=3)


BOTH_TOOLS = [LOOKUP_STOCK, LIST_WAREHOUSES]

# Opus 4.6 ignores a hook result of a hidden tool (docs/hooks.md#known-issues), so the tests that need the model
# to use that result run on Sonnet 5 instead when the matrix model is Opus 4.6.
_HOOK_RESULT_MODEL_SUBSTITUTIONS = {"anthropic.claude-opus-4-6-v1": "anthropic.claude-sonnet-5"}

# The test harness enables every DIAL file tool (enabled_tools="all"), so the model may reach for any of them.
FILE_TOOL_FUNCTIONS = [
    f"{INTERNAL_FILE_TOOL_NAME_PREFIX}{name}" for name in get_args(DialFilesToolName)
]

# test_visible_tool_is_called_by_model and test_hidden_tool_without_hook_is_unreachable are controls:
# they keep the hook tests from passing by accident.


@pytest.mark.requires_mcp
@pytest.mark.integration
@e2e_test(
    config_file_set="empty",
    no_cache=True,
    model_substitutions=_HOOK_RESULT_MODEL_SUBSTITUTIONS,
    toolsets=[_toolset(BOTH_TOOLS, hidden_from_model=[LOOKUP_STOCK])],
    hooks=[_stock_hook()],
    test_case=TstCase(
        "hidden_tool_hook_only",
        "A hook calls a hidden tool, the model gets the result without ever seeing the tool",
        similarity_threshold=SimilarityThreshold.LENIENT.value,
    )
    .add_user_message(
        user_message=STOCK_QUESTION,
        tool_calls=[_hidden_stock_call()],
        answer=["137"],
    )
    .add_tools_payload_check(absent=[LOOKUP_STOCK_FUNCTION], present=[LIST_WAREHOUSES_FUNCTION]),
)
def test_hidden_tool_is_callable_by_hook(client):
    pass


@pytest.mark.requires_mcp
@pytest.mark.integration
@e2e_test(
    config_file_set="empty",
    no_cache=True,
    model_substitutions=_HOOK_RESULT_MODEL_SUBSTITUTIONS,
    toolsets=[_toolset(BOTH_TOOLS, hidden_from_model=[LOOKUP_STOCK])],
    hooks=[_stock_hook()],
    test_case=TstCase(
        "hidden_tool_mixed_audience",
        "One toolset: the visible tool is used by the model, the hidden one is not offered",
        similarity_threshold=SimilarityThreshold.LENIENT.value,
    )
    .add_user_message(
        user_message=WAREHOUSES_QUESTION,
        tool_calls=[ToolCall(LIST_WAREHOUSES_FUNCTION), _hidden_stock_call()],
        answer=WAREHOUSES_ANSWER,
    )
    .add_tools_payload_check(absent=[LOOKUP_STOCK_FUNCTION], present=[LIST_WAREHOUSES_FUNCTION]),
)
def test_hidden_and_visible_tools_in_one_toolset(client):
    pass


@pytest.mark.requires_mcp
@pytest.mark.integration
@e2e_test(
    config_file_set="empty",
    no_cache=True,
    toolsets=[_toolset(BOTH_TOOLS, hidden_from_model=None)],
    test_case=TstCase(
        "hidden_tool_control_visible",
        "Control: without hidden_from_model the model reaches for the tool itself",
        similarity_threshold=SimilarityThreshold.LENIENT.value,
    )
    .add_user_message(
        user_message=STOCK_QUESTION,
        tool_calls=[ToolCall(LOOKUP_STOCK_FUNCTION).add_soft_argument_check("sku", ["SKU-1"])],
        answer=["137"],
    )
    .add_tools_payload_check(present=[LOOKUP_STOCK_FUNCTION]),
)
def test_visible_tool_is_called_by_model(client):
    pass


@pytest.mark.requires_mcp
@pytest.mark.integration
@e2e_test(
    config_file_set="empty",
    no_cache=True,
    toolsets=[_toolset(BOTH_TOOLS, hidden_from_model=[LOOKUP_STOCK])],
    test_case=TstCase(
        "hidden_tool_without_hook",
        "Control: hiding is what removes the tool, the model cannot learn the figure",
        similarity_threshold=SimilarityThreshold.LENIENT.value,
    )
    .add_user_message(
        user_message=STOCK_QUESTION,
        # Without the stock tool the model may look for the figure with whatever else is visible.
        tool_calls=[
            _hidden_stock_call(),
            _optional_call(LIST_WAREHOUSES_FUNCTION),
            *[_optional_call(name) for name in FILE_TOOL_FUNCTIONS],
        ],
        answer_not_contains=["137"],
    )
    .add_tools_payload_check(absent=[LOOKUP_STOCK_FUNCTION]),
)
def test_hidden_tool_without_hook_is_unreachable(client):
    pass


@pytest.mark.requires_mcp
@pytest.mark.integration
@e2e_test(
    config_file_set="empty",
    no_cache=True,
    toolsets=[
        _toolset(
            [*BOTH_TOOLS, MISSING_TOOL],
            hidden_from_model=[LOOKUP_STOCK, MISSING_TOOL],
        )
    ],
    hooks=[_stock_hook(tool_name=MISSING_TOOL)],
    test_case=TstCase(
        "hidden_tool_hook_on_missing_tool",
        "A hook on a tool the server does not provide does not fail the request",
        similarity_threshold=SimilarityThreshold.LENIENT.value,
    )
    .add_user_message(
        user_message=WAREHOUSES_QUESTION,
        tool_calls=[ToolCall(LIST_WAREHOUSES_FUNCTION)],
        answer=WAREHOUSES_ANSWER,
    )
    .add_tools_payload_check(
        absent=[LOOKUP_STOCK_FUNCTION, f"{TOOLSET_NAME}_{MISSING_TOOL}"],
        present=[LIST_WAREHOUSES_FUNCTION],
    ),
)
def test_hook_on_missing_hidden_tool_is_skipped(client):
    pass
