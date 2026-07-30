from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.agent_hooks._config_driven_hooks import _ConfigDrivenToolCallHook
from quickapp.common import ToolCallResult
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.config.hooks import HookEvent, ToolCallHookConfig, TTLRefreshCondition

_TIME_MODULE = "quickapp.agent_hooks._config_driven_hooks.time"


def _make_staged_tool(sanitized_name: str, run_content: str = "tool result") -> MagicMock:
    tool_fn = SimpleNamespace(name=sanitized_name)
    tool_open_ai = SimpleNamespace(function=tool_fn)
    tool_config = SimpleNamespace(open_ai_tool=tool_open_ai)
    result = ToolCallResult(content=run_content, content_type="text/plain")
    tool = MagicMock()
    tool.tool_config = tool_config
    tool.arun = AsyncMock(return_value=result)
    return tool


def _make_hook(
    tool_name: str,
    toolset_name: str | None = None,
    frequency: InjectionFrequency = InjectionFrequency.ALWAYS,
    arguments: dict | None = None,
    tools: list | None = None,
    ttl: int | None = None,
) -> _ConfigDrivenToolCallHook:
    config = ToolCallHookConfig(
        event=HookEvent.ON_REQUEST_START,
        tool_name=tool_name,
        toolset_name=toolset_name,
        frequency=frequency,
        arguments=arguments or {},
        refresh_condition=TTLRefreshCondition(ttl_minutes=ttl) if ttl is not None else None,
    )
    return _ConfigDrivenToolCallHook(tools or [], config)


def _make_tool_msg(call_id: str) -> Message:
    return Message(role=Role.TOOL, content="old result", tool_call_id=call_id)


def _make_assistant_msg(call_id: str, tool_name: str = "my_tool") -> Message:
    import json

    from aidial_sdk.chat_completion.request import FunctionCall, ToolCall

    return Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                id=call_id,
                type="function",
                function=FunctionCall(name=tool_name, arguments=json.dumps({})),
            )
        ],
    )


class TestGetToolName:
    @pytest.mark.asyncio
    async def test_without_toolset_name_returns_tool_name_verbatim(self):
        hook = _make_hook("My_Summarizer_tool")
        assert await hook.get_tool_name() == "My_Summarizer_tool"

    @pytest.mark.asyncio
    async def test_with_toolset_name_applies_sanitize_toolname(self):
        hook = _make_hook("get_memories", toolset_name="memory_server")
        assert await hook.get_tool_name() == "memory_server_get_memories"

    @pytest.mark.asyncio
    async def test_toolset_name_with_special_chars_sanitized(self):
        # sanitize_toolname replaces non-[a-zA-Z0-9_-] with '_'
        hook = _make_hook("get data", toolset_name="my server")
        assert await hook.get_tool_name() == "my_server_get_data"


class TestGetArguments:
    @pytest.mark.asyncio
    async def test_returns_config_arguments(self):
        hook = _make_hook("tool", arguments={"user_id": "abc", "limit": 10})
        assert await hook.get_arguments() == {"user_id": "abc", "limit": 10}

    @pytest.mark.asyncio
    async def test_defaults_to_empty_dict(self):
        hook = _make_hook("tool")
        assert await hook.get_arguments() == {}


class TestGetFrequency:
    @pytest.mark.asyncio
    async def test_returns_config_frequency_always(self):
        hook = _make_hook("tool", frequency=InjectionFrequency.ALWAYS)
        assert await hook.get_frequency([]) == InjectionFrequency.ALWAYS

    @pytest.mark.asyncio
    async def test_returns_config_frequency_append_if_changed(self):
        hook = _make_hook("tool", frequency=InjectionFrequency.APPEND_IF_CHANGED)
        assert await hook.get_frequency([]) == InjectionFrequency.APPEND_IF_CHANGED


class TestGetContent:
    @pytest.mark.asyncio
    async def test_delegates_to_staged_injector_and_returns_content(self):
        tool = _make_staged_tool("my_tool", "hello from tool")
        hook = _make_hook("my_tool", tools=[tool])
        result = await hook.get_content([])
        assert result == "hello from tool"
        tool.arun.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_none_when_tool_not_found(self):
        tool = _make_staged_tool("other_tool")
        hook = _make_hook("missing_tool", tools=[tool])
        result = await hook.get_content([])
        assert result is None
        tool.arun.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_none_and_logs_on_arun_exception(self):
        tool = _make_staged_tool("failing_tool")
        tool.arun = AsyncMock(side_effect=RuntimeError("network error"))
        hook = _make_hook("failing_tool", tools=[tool])
        result = await hook.get_content([])
        assert result is None

    @pytest.mark.asyncio
    async def test_passes_arguments_to_arun(self):
        tool = _make_staged_tool("arg_tool", "result")
        hook = _make_hook("arg_tool", arguments={"key": "value"}, tools=[tool])
        await hook.get_content([])
        _, kwargs = tool.arun.call_args
        assert kwargs.get("key") == "value"


class TestTransformIntegration:
    @pytest.mark.asyncio
    async def test_injects_pair_into_messages(self):
        tool = _make_staged_tool("my_tool", "injected content")
        hook = _make_hook("my_tool", frequency=InjectionFrequency.ALWAYS, tools=[tool])
        messages = [Message(role=Role.USER, content="hi")]
        result = await hook.transform(messages)
        # ASSISTANT tool_call + TOOL result + original USER
        assert len(result) == 3
        assert result[1].content == "injected content"
        assert result[2].content == "hi"


# ---------------------------------------------------------------------------
# Tests: TTL — make_call_id override
# ---------------------------------------------------------------------------


class TestTTLMakeCallId:
    def test_no_ttl_call_id_has_no_ttl_marker(self):
        hook = _make_hook("my_tool", ttl=None)
        call_id = hook.make_call_id("my_tool", {}, "content")
        assert "_ttl_" not in call_id

    def test_ttl_call_id_contains_ttl_marker(self):
        hook = _make_hook("my_tool", ttl=60)
        now = 1_700_000_000
        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = now
            call_id = hook.make_call_id("my_tool", {}, "content")
        assert "_ttl_" in call_id

    def test_ttl_expiry_is_now_plus_ttl_minutes_in_seconds(self):
        hook = _make_hook("my_tool", ttl=10)  # 10 minutes = 600 seconds
        now = 1_700_000_000
        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = now
            call_id = hook.make_call_id("my_tool", {}, "content")
        expected_expiry = now + 10 * 60
        assert f"_ttl_{expected_expiry:08x}" in call_id

    def test_explicit_ttl_expiry_not_overridden_when_provided(self):
        hook = _make_hook("my_tool", ttl=10)
        explicit_expiry = 99999999
        call_id = hook.make_call_id("my_tool", {}, "content", ttl_expiry_seconds=explicit_expiry)
        assert f"_ttl_{explicit_expiry:08x}" in call_id


# ---------------------------------------------------------------------------
# Tests: TTL — should_inject
# ---------------------------------------------------------------------------


class TestTTLShouldInject:
    @pytest.mark.asyncio
    async def test_no_ttl_always_returns_true(self):
        hook = _make_hook("my_tool", ttl=None)
        assert await hook.should_inject([]) is True

    @pytest.mark.asyncio
    async def test_ttl_returns_true_when_no_prior_injection(self):
        hook = _make_hook("my_tool", ttl=60)
        assert await hook.should_inject([Message(role=Role.USER, content="hi")]) is True

    @pytest.mark.asyncio
    async def test_ttl_returns_false_when_not_expired(self):
        hook = _make_hook("my_tool", ttl=60, frequency=InjectionFrequency.APPEND_IF_CHANGED)
        now = 1_700_000_000
        expiry = now + 3600  # injected 1h TTL, not yet expired

        call_id = hook.make_call_id("my_tool", {}, "result", ttl_expiry_seconds=expiry)
        messages = [
            Message(role=Role.USER, content="hi"),
            _make_assistant_msg(call_id, "my_tool"),
            _make_tool_msg(call_id),
        ]

        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = now + 10  # 10 seconds later, still valid
            result = await hook.should_inject(messages)
        assert result is False

    @pytest.mark.asyncio
    async def test_ttl_returns_true_when_expired(self):
        hook = _make_hook("my_tool", ttl=60, frequency=InjectionFrequency.APPEND_IF_CHANGED)
        now = 1_700_000_000
        expiry = now - 1  # already expired

        call_id = hook.make_call_id("my_tool", {}, "result", ttl_expiry_seconds=expiry)
        messages = [
            Message(role=Role.USER, content="hi"),
            _make_assistant_msg(call_id, "my_tool"),
            _make_tool_msg(call_id),
        ]

        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = now
            result = await hook.should_inject(messages)
        assert result is True

    @pytest.mark.asyncio
    async def test_ttl_returns_true_for_old_format_call_id_without_ttl_section(self):
        hook = _make_hook("my_tool", ttl=60)
        # Old-format call_id without _ttl_ section — treat as expired
        old_call_id = "synth_my_tool_abc123_def456"
        messages = [
            Message(role=Role.USER, content="hi"),
            _make_assistant_msg(old_call_id, "my_tool"),
            _make_tool_msg(old_call_id),
        ]
        assert await hook.should_inject(messages) is True


# ---------------------------------------------------------------------------
# Tests: TTL — end-to-end inject behaviour
# ---------------------------------------------------------------------------


class TestTTLEndToEnd:
    @pytest.mark.asyncio
    async def test_restamps_in_place_when_ttl_expired_and_content_unchanged(self):
        tool = _make_staged_tool("my_tool", "same result")
        hook = _make_hook(
            "my_tool", frequency=InjectionFrequency.APPEND_IF_CHANGED, tools=[tool], ttl=60
        )
        messages = [Message(role=Role.USER, content="hi")]

        inject_time = 1_700_000_000
        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = inject_time
            result = await hook.transform(messages)

        assert len(result) == 3
        old_call_id = result[0].tool_calls[0].id  # type: ignore[index]
        assert "_ttl_" in old_call_id

        # TTL expired
        expired_time = inject_time + 61 * 60
        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = expired_time
            result2 = await hook.transform(result)

        assert len(result2) == 3  # replaced in place, not appended
        new_call_id = result2[0].tool_calls[0].id  # type: ignore[index]
        assert new_call_id != old_call_id  # TTL expiry updated

    @pytest.mark.asyncio
    async def test_appends_when_ttl_expired_and_content_changed(self):
        tool = _make_staged_tool("my_tool", "v1")
        hook = _make_hook(
            "my_tool", frequency=InjectionFrequency.APPEND_IF_CHANGED, tools=[tool], ttl=60
        )
        messages = [Message(role=Role.USER, content="hi")]

        inject_time = 1_700_000_000
        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = inject_time
            result = await hook.transform(messages)

        assert len(result) == 3

        tool.arun = AsyncMock(return_value=ToolCallResult(content="v2", content_type="text/plain"))
        expired_time = inject_time + 61 * 60
        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = expired_time
            result2 = await hook.transform(result)

        assert len(result2) == 5  # old pair kept + new pair before last USER

    @pytest.mark.asyncio
    async def test_skips_when_ttl_not_expired(self):
        tool = _make_staged_tool("my_tool", "result")
        hook = _make_hook(
            "my_tool", frequency=InjectionFrequency.APPEND_IF_CHANGED, tools=[tool], ttl=60
        )
        messages = [Message(role=Role.USER, content="hi")]

        inject_time = 1_700_000_000
        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = inject_time
            result = await hook.transform(messages)

        assert len(result) == 3

        with patch(_TIME_MODULE) as mock_time:
            mock_time.time.return_value = inject_time + 30  # 30 seconds later, TTL = 60 min
            result2 = await hook.transform(result)

        assert result2 is result  # should_inject returned False → messages unchanged
        tool.arun.assert_awaited_once()  # only called once (first injection)
