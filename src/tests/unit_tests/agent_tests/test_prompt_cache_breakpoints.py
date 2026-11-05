from quickapp.core.agent._prompt_cache_breakpoints import _PromptCacheBreakpoints

_BREAKPOINT = {"cache_breakpoint": {}}


def _system() -> dict:
    return {"role": "system", "content": "prompt"}


def _user(custom_fields: dict | None = None) -> dict:
    message: dict = {"role": "user", "content": "hi"}
    if custom_fields is not None:
        message["custom_fields"] = custom_fields
    return message


def _static_tool() -> dict:
    return {"type": "static_function", "static_function": {"name": "s"}}


def _tool(custom_fields: dict | None = None) -> dict:
    tool: dict = {"type": "function", "function": {"name": "t"}}
    if custom_fields is not None:
        tool["custom_fields"] = custom_fields
    return tool


def test_marks_system_last_message_and_last_tool():
    messages = [_system(), _user(), _user()]
    tools = [_tool(), _tool()]

    _PromptCacheBreakpoints().apply(messages, tools)

    assert messages[0]["custom_fields"] == _BREAKPOINT
    assert "custom_fields" not in messages[1]
    assert messages[2]["custom_fields"] == _BREAKPOINT
    assert "custom_fields" not in tools[0]
    assert tools[1]["custom_fields"] == _BREAKPOINT


def test_system_message_alone_is_marked_once():
    messages = [_system()]

    _PromptCacheBreakpoints().apply(messages, [])

    assert messages[0]["custom_fields"] == _BREAKPOINT


def test_without_system_message_marks_last_message():
    messages = [_user(), _user()]

    _PromptCacheBreakpoints().apply(messages, [])

    assert "custom_fields" not in messages[0]
    assert messages[1]["custom_fields"] == _BREAKPOINT


def test_static_tool_last_marks_the_last_function_tool():
    """The SDK schema gives static tools no ``custom_fields``; adapters would reject one."""
    tools = [_tool(), _static_tool()]

    _PromptCacheBreakpoints().apply([_system()], tools)

    assert tools[0]["custom_fields"] == _BREAKPOINT
    assert tools[1] == _static_tool()


def test_only_static_tools_marks_no_tool():
    tools = [_static_tool()]

    _PromptCacheBreakpoints().apply([_system(), _user()], tools)

    assert tools == [_static_tool()]


def test_does_not_mutate_marked_items():
    """Tool dicts are shared across model calls; the payload gets a marked copy."""
    tool = _tool({"configuration": {}})
    tools = [tool]

    _PromptCacheBreakpoints().apply([_system()], tools)

    assert tool == _tool({"configuration": {}})
    assert tools[0]["custom_fields"] == {"configuration": {}, "cache_breakpoint": {}}


def test_keeps_other_custom_fields():
    messages = [_system(), _user({"configuration": {}}), _user({"configuration": {}})]
    tools = [_tool({"configuration": {}})]

    _PromptCacheBreakpoints().apply(messages, tools)

    assert messages[0]["custom_fields"] == _BREAKPOINT
    assert messages[2]["custom_fields"] == {"configuration": {}, "cache_breakpoint": {}}
    assert tools[0]["custom_fields"] == {"configuration": {}, "cache_breakpoint": {}}
