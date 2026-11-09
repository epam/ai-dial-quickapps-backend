"""Tests for the internal_run_task tool.

A task runs its own orchestrator loop against a compiled manifest, in a DI request
scope isolated from the delegating agent's, limited to the tools the call named.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Choice, Message, Role
from fastapi_injector import RequestScopeFactory
from injector import Binder, Injector, ProviderOf, inject

from quickapp.common import ACCEPT_LANGUAGE, TIMEZONE_HEADER_VALUE, StagedBaseTool
from quickapp.common.base_initializer import InitializerType, invoke_initializers
from quickapp.common.deployment_usage import DeploymentUsage
from quickapp.common.exceptions import (
    FallbackAgentStopException,
    InitializationException,
    InvalidToolCallParameterException,
    ToolInitializationException,
)
from quickapp.common.exceptions.orchestrator_exceed_max_iterations import (
    OrchestratorExceedMaxIterationsException,
)
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.tool_allowlist import ToolAllowlist
from quickapp.common.tool_names import (
    INTERNAL_FILE_LIST_TOOL_NAME,
    INTERNAL_FILE_READ_LINES_TOOL_NAME,
    INTERNAL_RUN_TASK_TOOL_NAME,
    INTERNAL_TIMEAWARENESS_CURRENT_TIMESTAMP_TOOL_NAME,
    INTERNAL_TOOL_SEARCH_TOOL_NAME,
)
from quickapp.config.application import ApplicationConfig
from quickapp.config.hooks import HookEvent, ToolCallHookConfig
from quickapp.config.run_task import RunTaskConfig
from quickapp.config.starters import ConversationStarter, ConversationStartersConfig
from quickapp.config.tool_discovery import ToolDiscoveryConfig
from quickapp.core.agent.models import OpenAiToolConfigDict
from quickapp.core.agent.orchestrator import Orchestrator
from quickapp.core.application import _InitializationErrorHandler, _RequestContext
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService
from quickapp.task_tooling._exceptions import TaskToolErrorException
from quickapp.task_tooling._manifest_compiler import compile_task_manifest
from quickapp.task_tooling._run_task_settings import RunTaskSettings, TaskSemaphore
from quickapp.task_tooling._task_prompt import TASK_SYSTEM_PROMPT
from quickapp.task_tooling._task_runner import TaskRunner, _task_timeout
from quickapp.task_tooling._tool_catalogue import IMPLICIT_TASK_TOOL_NAMES
from tests.unit_tests.common.common import create_app_configuration


def _parent_config(run_task: RunTaskConfig | None = None) -> ApplicationConfig:
    config = create_app_configuration([])
    assert config.features is not None
    config.features.run_task = run_task or RunTaskConfig(enabled=True)
    return config


class _FakeRun:
    """What `TaskRunner` reads from a finished run."""

    usage_statistics: list[DeploymentUsage] = []


class _FakeOrchestrator(_FakeRun):
    """Records what the child scope resolved, and answers."""

    seen: list[ApplicationConfig] = []
    seen_tools: list[list[str]] = []
    seen_user_locale: list[tuple[str | None, str | None]] = []

    @inject
    def __init__(
        self,
        config: ApplicationConfig,
        messages: MessagesMixin,
        accept_language: ACCEPT_LANGUAGE,
        timezone_header_value: TIMEZONE_HEADER_VALUE,
        openai_tools: ProviderOf[list[OpenAiToolConfigDict]],
    ) -> None:
        self._config = config
        self._messages = messages
        self._user_locale = (accept_language, timezone_header_value)
        self._openai_tools = openai_tools

    async def invoke(self) -> None:
        cls = type(self)
        cls.seen.append(self._config)
        cls.seen_tools.append(sorted(t["function"]["name"] for t in self._openai_tools.get()))
        cls.seen_user_locale.append(self._user_locale)
        self._messages.append_message(
            Message(role=Role.ASSISTANT, content="42 sources, one answer.")
        )


@pytest.fixture(autouse=True)
def _reset_fake_orchestrator(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
    _FakeOrchestrator.seen = []
    _FakeOrchestrator.seen_tools = []
    _FakeOrchestrator.seen_user_locale = []


def _test_injector() -> Injector:
    from quickapp.app_factory import AppFactory

    # The real completion initializers run in the child scope — only the DIAL Core
    # round-trip for deployment metadata is stubbed out.
    core_service = MagicMock(spec=ToolConfigCoreService)
    core_service.get_deployment_metadata = AsyncMock(return_value=MagicMock(defaults=None))

    def overrides(binder: Binder) -> None:
        binder.bind(Orchestrator, to=_FakeOrchestrator)  # type: ignore[type-abstract,arg-type]
        binder.bind(ToolConfigCoreService, to=core_service)

    return Injector([*AppFactory.build_di_modules(), overrides])


async def _enter_parent_scope(injector: Injector, config: ApplicationConfig) -> _RequestContext:
    from pydantic import SecretStr

    context = injector.get(_RequestContext)
    context.api_key = SecretStr("key")
    context.bearer = None
    context.forwarded_headers = {}
    context.application_config = config
    context.messages = [Message(role=Role.USER, content="do the thing")]
    return context


def _run_task_tool(injector: Injector) -> StagedBaseTool | None:
    tools = injector.get(list[StagedBaseTool])
    offered = [t for t in tools if t.openai_function_name() == INTERNAL_RUN_TASK_TOOL_NAME]
    return offered[0] if offered else None


async def _call_tool(injector: Injector, **kwargs):
    await invoke_initializers(injector, InitializerType.completion)
    tool = _run_task_tool(injector)
    assert tool is not None
    return await tool._run_in_stage_async(**kwargs)


# --- manifest ---------------------------------------------------------------------


def test_manifest_compilation_narrows_the_task():
    parent = _parent_config(RunTaskConfig(enabled=True, max_iterations=3))
    parent.conversation_starters = ConversationStartersConfig(
        intro_text="Hi", starters=[ConversationStarter(title="hi", text="hi")]
    )

    manifest = compile_task_manifest(parent, RunTaskConfig(max_iterations=3), explicit_tools=False)

    assert manifest is not parent
    # The task prompt comes first; the app's rules still apply.
    assert manifest.orchestrator.system_prompt.content == (
        f"{TASK_SYSTEM_PROMPT}\n\n## Rules from the application\n\ntest"
    )
    assert manifest.orchestrator.max_iterations == 3
    assert manifest.features is not None and manifest.features.run_task is None
    assert manifest.conversation_starters is None
    # The parent is untouched.
    assert parent.features is not None and parent.features.run_task is not None
    assert parent.orchestrator.system_prompt.content == "test"


def test_an_app_without_a_prompt_gets_the_task_prompt_alone():
    parent = _parent_config()
    parent.orchestrator.system_prompt.content = "  "
    manifest = compile_task_manifest(parent, RunTaskConfig(), explicit_tools=False)
    assert manifest.orchestrator.system_prompt.content == TASK_SYSTEM_PROMPT


def test_unset_iteration_budget_inherits_the_parent():
    parent = _parent_config()
    manifest = compile_task_manifest(parent, RunTaskConfig(), explicit_tools=False)
    assert manifest.orchestrator.max_iterations == parent.orchestrator.max_iterations


@pytest.mark.parametrize("explicit_tools", [True, False])
def test_an_explicit_tool_list_turns_tool_discovery_off(explicit_tools):
    parent = _parent_config()
    parent.orchestrator.tool_discovery = ToolDiscoveryConfig()

    manifest = compile_task_manifest(parent, RunTaskConfig(), explicit_tools=explicit_tools)

    assert (manifest.orchestrator.tool_discovery is None) is explicit_tools


def test_on_completion_hooks_do_not_run_in_a_task():
    parent = _parent_config()
    parent.hooks = [
        ToolCallHookConfig(event=HookEvent.ON_REQUEST_START, tool_name="inject"),
        ToolCallHookConfig(event=HookEvent.ON_COMPLETION, tool_name="notify"),
    ]

    manifest = compile_task_manifest(parent, RunTaskConfig(), explicit_tools=False)

    assert [h.event for h in manifest.hooks or []] == [HookEvent.ON_REQUEST_START]
    assert len(parent.hooks) == 2


# --- tool offering ----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("run_task", [None, RunTaskConfig(enabled=False)])
async def test_no_tool_unless_enabled(run_task):
    injector = _test_injector()
    config = create_app_configuration([])
    assert config.features is not None
    config.features.run_task = run_task

    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, config)
        await invoke_initializers(injector, InitializerType.completion)
        assert _run_task_tool(injector) is None


@pytest.mark.asyncio
async def test_tool_is_offered_when_enabled():
    injector = _test_injector()
    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        await invoke_initializers(injector, InitializerType.completion)
        assert _run_task_tool(injector) is not None


def test_run_task_is_a_preview_field(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "false")
    config = ApplicationConfig.model_validate(
        {
            **_parent_config().model_dump(mode="json", exclude_none=True),
            "features": {"run_task": {"enabled": True}},
        }
    )
    assert config.features is not None and config.features.run_task is None


# --- tools argument ---------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("tools", [["inherit"], "inherit"])
async def test_inherit_gives_the_task_every_tool_but_run_task(tools):
    injector = _test_injector()
    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        result = await _call_tool(injector, name="Look around", prompt="Go.", tools=tools)

    assert result.content == "42 sources, one answer."
    [child_tools] = _FakeOrchestrator.seen_tools
    assert INTERNAL_TIMEAWARENESS_CURRENT_TIMESTAMP_TOOL_NAME in child_tools
    assert INTERNAL_FILE_LIST_TOOL_NAME in child_tools
    assert INTERNAL_RUN_TASK_TOOL_NAME not in child_tools


@pytest.mark.asyncio
async def test_a_list_gives_the_task_only_the_named_tools():
    injector = _test_injector()
    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        await _call_tool(
            injector,
            name="Read a file",
            prompt="Read it.",
            tools=[INTERNAL_FILE_LIST_TOOL_NAME, INTERNAL_FILE_READ_LINES_TOOL_NAME],
        )

    [child_tools] = _FakeOrchestrator.seen_tools
    # Implicit readers are added too, but only when the parent has them.
    assert set(child_tools) - IMPLICIT_TASK_TOOL_NAMES == {INTERNAL_FILE_LIST_TOOL_NAME}
    assert INTERNAL_FILE_READ_LINES_TOOL_NAME in child_tools


@pytest.mark.asyncio
async def test_an_explicit_list_can_read_offloaded_results():
    injector = _test_injector()
    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        await _call_tool(
            injector,
            name="Clock",
            prompt="What time is it?",
            tools=[INTERNAL_TIMEAWARENESS_CURRENT_TIMESTAMP_TOOL_NAME],
        )

    [child_tools] = _FakeOrchestrator.seen_tools
    # An offloaded tool result points at the file readers.
    assert INTERNAL_FILE_READ_LINES_TOOL_NAME in child_tools


@pytest.mark.asyncio
async def test_an_empty_list_gives_the_task_no_capability_tools():
    injector = _test_injector()
    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        await _call_tool(injector, name="Think", prompt="Reason.", tools=[])

    [child_tools] = _FakeOrchestrator.seen_tools
    assert set(child_tools) <= IMPLICIT_TASK_TOOL_NAMES


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unknown", ["no_such_tool", INTERNAL_RUN_TASK_TOOL_NAME, INTERNAL_TOOL_SEARCH_TOOL_NAME]
)
async def test_an_unknown_tool_fails_the_call_without_running(unknown):
    injector = _test_injector()
    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await _call_tool(injector, name="Bad", prompt="Go.", tools=[unknown])

    message = str(excinfo.value)
    assert unknown in message
    # The valid names are listed so the LLM can retry.
    assert INTERNAL_FILE_LIST_TOOL_NAME in message
    assert _FakeOrchestrator.seen == []


@pytest.mark.asyncio
async def test_inherit_mixed_with_tool_names_fails_the_call_without_running():
    injector = _test_injector()
    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await _call_tool(
                injector, name="Mix", prompt="Go.", tools=["inherit", INTERNAL_FILE_LIST_TOOL_NAME]
            )

    assert "must be the only item" in str(excinfo.value)
    assert _FakeOrchestrator.seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "Label", "prompt": "Go.", "tools": "everything"},
        {"name": "Label", "prompt": "Go.", "tools": [1, 2]},
        {"name": "Label", "prompt": "Go."},
        {"name": "Label", "prompt": "  ", "tools": ["inherit"]},
        {"name": "", "prompt": "Go.", "tools": ["inherit"]},
    ],
)
async def test_malformed_arguments_fail_the_call_without_running(kwargs):
    injector = _test_injector()
    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        with pytest.raises(InvalidToolCallParameterException):
            await _call_tool(injector, **kwargs)

    assert _FakeOrchestrator.seen == []


# --- running ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_runs_in_an_isolated_request_scope():
    injector = _test_injector()
    parent_config = _parent_config()

    async with injector.get(RequestScopeFactory).create_scope():
        parent_context = await _enter_parent_scope(injector, parent_config)

        task = await injector.get(TaskRunner).run(
            "Find out who broke the build.", ToolAllowlist(), None
        )

        assert task.answer == "42 sources, one answer."
        [child_config] = _FakeOrchestrator.seen
        assert child_config is not parent_config
        assert child_config.orchestrator.system_prompt.content.startswith(TASK_SYSTEM_PROMPT)

        # The parent scope is untouched.
        assert injector.get(_RequestContext) is parent_context
        assert parent_context.application_config is parent_config
        assert [m.content for m in parent_context.messages] == ["do the thing"]


@pytest.mark.asyncio
async def test_task_log_counts_only_the_requested_tools(caplog):
    injector = _test_injector()

    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        with caplog.at_level("INFO"):
            await injector.get(TaskRunner).run(
                "Find out.", ToolAllowlist(names=IMPLICIT_TASK_TOOL_NAMES), None
            )

    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Running task")]
    assert "tools=0" in line


@pytest.mark.asyncio
async def test_task_lifecycle_logs_are_tagged_as_a_task(caplog):
    injector = _test_injector()

    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        with caplog.at_level("INFO"):
            await injector.get(TaskRunner).run("Find out.", ToolAllowlist(), None)

    lifecycle = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith(("Request received", "Request initialized"))
    ]
    assert len(lifecycle) == 2
    assert all("task=True" in line for line in lifecycle)


@pytest.mark.asyncio
async def test_task_inherits_the_users_language_and_time_zone():
    injector = _test_injector()
    async with injector.get(RequestScopeFactory).create_scope():
        parent_context = await _enter_parent_scope(injector, _parent_config())
        parent_context.accept_language = "de"
        parent_context.timezone_header_value = "Europe/Berlin"

        await injector.get(TaskRunner).run("Find out.", ToolAllowlist(), None)

    assert _FakeOrchestrator.seen_user_locale == [("de", "Europe/Berlin")]


@pytest.mark.asyncio
async def test_parallel_tasks_do_not_share_scope():
    injector = _test_injector()
    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        runner = injector.get(TaskRunner)
        await asyncio.gather(
            runner.run("one", ToolAllowlist(), None),
            runner.run("two", ToolAllowlist(names=frozenset({INTERNAL_FILE_LIST_TOOL_NAME})), None),
        )

    assert len(_FakeOrchestrator.seen) == 2
    inherit, narrowed = sorted(_FakeOrchestrator.seen_tools, key=len, reverse=True)
    assert INTERNAL_TIMEAWARENESS_CURRENT_TIMESTAMP_TOOL_NAME in inherit
    assert narrowed == [INTERNAL_FILE_LIST_TOOL_NAME]


class _SilentOrchestrator(_FakeRun):
    """Ends without a final message."""

    @inject
    def __init__(self) -> None:
        pass

    async def invoke(self) -> None:
        return


class _BlankOrchestrator(_FakeRun):
    """Answers with the placeholder the real orchestrator stores for an empty reply."""

    @inject
    def __init__(self, messages: MessagesMixin) -> None:
        self._messages = messages

    async def invoke(self) -> None:
        self._messages.append_message(Message(role=Role.ASSISTANT, content=" "))


class _ExhaustedOrchestrator(_FakeRun):
    @inject
    def __init__(self) -> None:
        pass

    async def invoke(self) -> None:
        raise OrchestratorExceedMaxIterationsException()


async def _run_failing_task(orchestrator: type) -> TaskToolErrorException:
    injector = _test_injector()
    injector.binder.bind(Orchestrator, to=orchestrator)  # type: ignore[type-abstract]

    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        with pytest.raises(TaskToolErrorException) as excinfo:
            await injector.get(TaskRunner).run("Find out.", ToolAllowlist(), None)
    return excinfo.value


@pytest.mark.asyncio
@pytest.mark.parametrize("orchestrator", [_SilentOrchestrator, _BlankOrchestrator])
async def test_task_without_an_answer_fails_the_tool_call(orchestrator):
    error = await _run_failing_task(orchestrator)
    assert "without an answer" in error.user_facing_message


@pytest.mark.asyncio
async def test_task_out_of_iterations_fails_the_tool_call():
    error = await _run_failing_task(_ExhaustedOrchestrator)
    assert "max_iterations budget" in error.user_facing_message


class _StoppingOrchestrator(_FakeRun):
    """A tool in the task hit a `hard_stop` fallback."""

    @inject
    def __init__(self) -> None:
        pass

    async def invoke(self) -> None:
        raise FallbackAgentStopException("child-call")


@pytest.mark.asyncio
async def test_a_hard_stop_in_a_task_stops_the_delegating_turn():
    injector = _test_injector()
    injector.binder.bind(Orchestrator, to=_StoppingOrchestrator)  # type: ignore[type-abstract,arg-type]

    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        with pytest.raises(FallbackAgentStopException):
            await _call_tool(injector, name="Stop", prompt="Go.", tools=["inherit"])


class _SpendingOrchestrator(_FakeRun):
    usage_statistics = [
        DeploymentUsage(model_name="gpt-x", prompt_tokens=3, completion_tokens=4),
        DeploymentUsage(
            deployment_id="weather", deployment_name="weather", prompt_tokens=1, completion_tokens=2
        ),
    ]

    @inject
    def __init__(self, messages: MessagesMixin) -> None:
        self._messages = messages

    async def invoke(self) -> None:
        self._messages.append_message(Message(role=Role.ASSISTANT, content="spent"))


@pytest.mark.asyncio
async def test_task_usage_reaches_the_delegating_turn():
    injector = _test_injector()
    injector.binder.bind(Orchestrator, to=_SpendingOrchestrator)  # type: ignore[type-abstract,arg-type]

    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        result = await _call_tool(injector, name="Spend", prompt="Go.", tools=["inherit"])

    own, nested = result.usage
    # The task's model calls get their own row, apart from the agent's.
    assert not own.is_orchestrator()
    assert (own.deployment_id, own.prompt_tokens, own.completion_tokens) == ("gpt-x", 3, 4)
    assert nested.deployment_name == "weather"


class _SlowOrchestrator(_FakeRun):
    @inject
    def __init__(self) -> None:
        pass

    async def invoke(self) -> None:
        await asyncio.sleep(30)


@pytest.mark.asyncio
async def test_task_exceeding_its_budget_fails_the_tool_call():
    injector = _test_injector()
    injector.binder.bind(Orchestrator, to=_SlowOrchestrator)  # type: ignore[type-abstract,arg-type]
    config = _parent_config(RunTaskConfig(enabled=True, timeout_seconds=0.05))

    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, config)
        with pytest.raises(TaskToolErrorException) as excinfo:
            await injector.get(TaskRunner).run("Take your time.", ToolAllowlist(), None)

    assert "0.05s budget" in excinfo.value.user_facing_message


class _TimingOutOrchestrator(_FakeRun):
    @inject
    def __init__(self) -> None:
        pass

    async def invoke(self) -> None:
        raise TimeoutError("an upstream call timed out")


@pytest.mark.asyncio
async def test_a_timeout_inside_the_task_is_not_reported_as_the_budget_running_out():
    injector = _test_injector()
    injector.binder.bind(Orchestrator, to=_TimingOutOrchestrator)  # type: ignore[type-abstract,arg-type]
    config = _parent_config(RunTaskConfig(enabled=True, timeout_seconds=30))

    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, config)
        with pytest.raises(TimeoutError, match="upstream call"):
            await injector.get(TaskRunner).run("Find out.", ToolAllowlist(), None)


def test_an_app_may_shorten_the_admin_ceiling_but_not_extend_it():
    settings = RunTaskSettings(RUN_TASK_TIMEOUT_SECONDS=60)

    for declared, expected in ((None, 60), (10, 10), (600, 60)):
        assert _task_timeout(settings, RunTaskConfig(timeout_seconds=declared)) == expected


class _ConcurrencyProbe(_FakeRun):
    live = 0
    peak = 0

    @inject
    def __init__(self, messages: MessagesMixin) -> None:
        self._messages = messages

    async def invoke(self) -> None:
        cls = type(self)
        cls.live += 1
        cls.peak = max(cls.peak, cls.live)
        try:
            await asyncio.sleep(0.01)
            self._messages.append_message(Message(role=Role.ASSISTANT, content="done"))
        finally:
            cls.live -= 1


@pytest.mark.asyncio
async def test_parallel_tasks_are_capped(monkeypatch):
    monkeypatch.setenv("RUN_TASK_MAX_CONCURRENT", "2")
    _ConcurrencyProbe.live = 0
    _ConcurrencyProbe.peak = 0

    injector = _test_injector()
    injector.binder.bind(Orchestrator, to=_ConcurrencyProbe)  # type: ignore[type-abstract,arg-type]

    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        runner = injector.get(TaskRunner)
        results = await asyncio.gather(
            *(runner.run(f"task {i}", ToolAllowlist(), None) for i in range(6))
        )

    # Every task still completed — excess ones queue rather than fail.
    assert [r.answer for r in results] == ["done"] * 6
    assert _ConcurrencyProbe.peak == 2


class _SteadyOrchestrator(_FakeRun):
    @inject
    def __init__(self, messages: MessagesMixin) -> None:
        self._messages = messages

    async def invoke(self) -> None:
        await asyncio.sleep(0.6)
        self._messages.append_message(Message(role=Role.ASSISTANT, content="done"))


@pytest.mark.asyncio
async def test_time_in_the_queue_does_not_count_against_the_budget(monkeypatch):
    monkeypatch.setenv("RUN_TASK_MAX_CONCURRENT", "1")
    injector = _test_injector()
    injector.binder.bind(Orchestrator, to=_SteadyOrchestrator)  # type: ignore[type-abstract,arg-type]
    config = _parent_config(RunTaskConfig(enabled=True, timeout_seconds=1.0))

    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, config)
        runner = injector.get(TaskRunner)
        # The second task waits ~0.6s for the slot, then runs 0.6s: over the
        # budget end to end, within it once admitted (0.4s headroom for slow CI).
        results = await asyncio.gather(*(runner.run(p, ToolAllowlist(), None) for p in ("a", "b")))

    assert [r.answer for r in results] == ["done", "done"]


@pytest.mark.asyncio
async def test_the_wait_for_a_slot_is_bounded(monkeypatch):
    monkeypatch.setenv("RUN_TASK_MAX_CONCURRENT", "1")
    injector = _test_injector()
    config = _parent_config(RunTaskConfig(enabled=True, timeout_seconds=0.05))

    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, config)
        async with injector.get(TaskSemaphore).hold(wait_seconds=1):
            with pytest.raises(TaskToolErrorException) as excinfo:
                await injector.get(TaskRunner).run("Find out.", ToolAllowlist(), None)

    assert "Too many tasks" in excinfo.value.user_facing_message
    assert _FakeOrchestrator.seen == []


def test_task_prompt_tells_the_model_to_use_platform_tool_results():
    # Workaround for the hook-result issue in docs/hooks.md#known-issues.
    assert "executed on your behalf" in TASK_SYSTEM_PROMPT


class _PlottingOrchestrator(_FakeRun):
    @inject
    def __init__(self, messages: MessagesMixin, choice: Choice) -> None:
        self._messages = messages
        self._choice = choice

    async def invoke(self) -> None:
        self._choice.add_attachment(type="image/png", title="chart", url="files/x/chart.png")
        self._messages.append_message(Message(role=Role.ASSISTANT, content="Chart attached."))


@pytest.mark.asyncio
async def test_a_task_can_return_a_file():
    injector = _test_injector()
    injector.binder.bind(Orchestrator, to=_PlottingOrchestrator)  # type: ignore[type-abstract,arg-type]

    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        task = await injector.get(TaskRunner).run("Plot the results.", ToolAllowlist(), None)

    assert task.answer == "Chart attached."
    assert [a.url for a in task.attachments] == ["files/x/chart.png"]


class _RecordingErrorHandler:
    seen: list[int] = []

    @inject
    def __init__(self, exceptions: ProviderOf[list[InitializationException]]) -> None:
        self.__exceptions = exceptions

    def handle_initialization_issues(self) -> None:
        type(self).seen.append(len(self.__exceptions.get()))


@pytest.mark.asyncio
async def test_task_initialization_issues_reach_the_handler():
    _RecordingErrorHandler.seen = []
    injector = _test_injector()
    injector.binder.bind(
        _InitializationErrorHandler, to=_RecordingErrorHandler  # type: ignore[arg-type]
    )
    injector.binder.multibind(
        list[InitializationException],
        to=[ToolInitializationException(message="tool is down", tool_name="broken")],
    )

    async with injector.get(RequestScopeFactory).create_scope():
        await _enter_parent_scope(injector, _parent_config())
        task = await injector.get(TaskRunner).run("Find out.", ToolAllowlist(), None)

    assert task.answer == "42 sources, one answer."
    # Exactly one check ran — in the task's scope — and it saw the failed tool.
    assert _RecordingErrorHandler.seen == [1]
