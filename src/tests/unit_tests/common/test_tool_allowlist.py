from unittest.mock import MagicMock

from aidial_sdk.chat_completion.request import StaticFunction, StaticTool

from quickapp.common.tool_allowlist import ToolAllowlist


def _tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.openai_function_name.return_value = name
    return tool


def _static(name: str) -> StaticTool:
    return StaticTool(type="static_function", static_function=StaticFunction(name=name))


def test_no_names_allows_everything():
    allowlist = ToolAllowlist()
    tools = [_tool("a"), _tool("b")]
    statics = [_static("s")]

    assert allowlist.allows("anything")
    assert allowlist.filter_tools(tools) == tools
    assert allowlist.filter_static(statics) == statics


def test_names_narrow_staged_and_static_tools():
    allowlist = ToolAllowlist(names=frozenset({"a", "s"}))
    a, b = _tool("a"), _tool("b")

    assert allowlist.filter_tools([a, b]) == [a]
    assert [
        t.static_function.name for t in allowlist.filter_static([_static("s"), _static("x")])
    ] == ["s"]


def test_a_nameless_tool_is_not_allowed_by_a_narrowed_list():
    assert not ToolAllowlist(names=frozenset({"a"})).allows(None)
    assert ToolAllowlist().allows(None)
