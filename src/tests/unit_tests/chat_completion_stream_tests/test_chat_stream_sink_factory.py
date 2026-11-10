from types import SimpleNamespace

import pytest

from quickapp.common.chat_completion_stream.chat_stream_sink_factory import ChatStreamSinkFactory
from quickapp.common.tool_allowlist import ToolAllowlist
from tests.unit_tests.common.common import make_provider


def _stub_tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(openai_function_name=lambda: name)


@pytest.mark.parametrize(
    "allowlist, expected",
    [
        (ToolAllowlist(names=frozenset({"allowed"})), ["allowed"]),
        (ToolAllowlist(), ["allowed", "other"]),
    ],
)
def test_only_allowlisted_tools_can_open_a_stage(allowlist, expected):
    tools = [_stub_tool("allowed"), _stub_tool("other")]
    factory = ChatStreamSinkFactory(tools=make_provider(tools), allowlist=make_provider(allowlist))

    assert [tool.openai_function_name() for tool in factory._tools()] == expected
