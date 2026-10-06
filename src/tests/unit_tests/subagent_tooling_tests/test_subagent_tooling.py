"""Tests for in-process subagent spawning.

Cover the guarantees the feature rests on: a spawned subagent runs its own
orchestrator loop against its own compiled manifest — a declared type's, or the
general-purpose one scoped by the call — in a DI request scope isolated from the
coordinator's, and never touches the coordinator's state.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Choice, Message, Role
from fastapi_injector import RequestScopeFactory
from injector import Binder, Injector, ProviderOf, inject
from pydantic import SecretStr, ValidationError

from quickapp.common import StagedBaseTool
from quickapp.common.base_initializer import InitializerType, invoke_initializers
from quickapp.common.exceptions import (
    InitializationException,
    InvalidToolCallParameterException,
    ToolInitializationException,
)
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.config.application import ApplicationConfig
from quickapp.config.context import UserDefinedContextConfig
from quickapp.config.starters import ConversationStarter, ConversationStartersConfig
from quickapp.config.subagent import (
    GENERAL_PURPOSE_SUBAGENT_NAME,
    GeneralPurposeSubagentConfig,
    SubagentConfig,
    SubagentsConfig,
)
from quickapp.config.toolsets.internal import InternalToolSet
from quickapp.core.agent.orchestrator import Orchestrator
from quickapp.core.application import _InitializationErrorHandler, _RequestContext
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService
from quickapp.subagent_tooling._builtin_subagents import (
    GENERAL_PURPOSE_SYSTEM_PROMPT,
    general_purpose_subagent,
)
from quickapp.subagent_tooling._exceptions import (
    SubagentToolErrorException,
    SubagentToolSetResolutionError,
)
from quickapp.subagent_tooling._manifest_compiler import compile_subagent_manifest
from quickapp.subagent_tooling._subagent_settings import SubagentSettings
from quickapp.subagent_tooling._subagent_spawner import SubagentSpawner
from quickapp.subagent_tooling._tool_config import TASK_TOOL_NAME
from tests.unit_tests.common.common import create_app_configuration

RESEARCHER = SubagentConfig(
    name="researcher",
    description="Digs through sources and reports findings.",
    system_prompt="You are a researcher. Answer tersely.",
    tool_sets=["research"],
    max_iterations=3,
)

GENERAL_PURPOSE = GeneralPurposeSubagentConfig()


def _parent_config(subagents: SubagentsConfig | None = None) -> ApplicationConfig:
    config = create_app_configuration(
        [
            InternalToolSet(name="research", tools=[]),
            InternalToolSet(name="reporting", tools=[]),
        ]
    )
    assert config.features is not None
    config.features.subagents = subagents or SubagentsConfig(enabled=True, types=[RESEARCHER])
    return config


class _FakeOrchestrator:
    """Records the manifest the child scope resolved, and answers."""

    seen: list[ApplicationConfig] = []

    @inject
    def __init__(self, config: ApplicationConfig, messages: MessagesMixin) -> None:
        self._config = config
        self._messages = messages

    async def invoke(self) -> None:
        type(self).seen.append(self._config)
        self._messages.append_message(
            Message(role=Role.ASSISTANT, content="42 sources, one answer.")
        )


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


async def _enter_coordinator_scope(
    injector: Injector, config: ApplicationConfig
) -> _RequestContext:
    context = injector.get(_RequestContext)
    context.api_key = SecretStr("key")
    context.bearer = None
    context.forwarded_headers = {}
    context.application_config = config
    context.messages = [Message(role=Role.USER, content="do the thing")]
    return context


def _spawn_tool(injector: Injector) -> StagedBaseTool | None:
    tools = injector.get(list[StagedBaseTool])
    offered = [t for t in tools if t.openai_function_name() == TASK_TOOL_NAME]
    return offered[0] if offered else None


# --- config -----------------------------------------------------------------------


def test_a_declared_type_may_not_shadow_the_general_purpose_name():
    with pytest.raises(ValidationError, match="unique"):
        SubagentsConfig(
            enabled=True,
            types=[RESEARCHER.model_copy(update={"name": GENERAL_PURPOSE_SUBAGENT_NAME})],
        )


def test_declared_type_names_must_be_unique():
    with pytest.raises(ValidationError, match="researcher"):
        SubagentsConfig(enabled=True, types=[RESEARCHER, RESEARCHER])


def test_the_reserved_name_is_free_once_general_purpose_is_off():
    config = SubagentsConfig(
        enabled=True,
        general_purpose=None,
        types=[RESEARCHER.model_copy(update={"name": GENERAL_PURPOSE_SUBAGENT_NAME})],
    )

    assert [s.name for s in config.types] == [GENERAL_PURPOSE_SUBAGENT_NAME]


# --- manifest compilation ---------------------------------------------------------


def test_manifest_compilation_narrows_the_spoke():
    parent = _parent_config()
    parent.contexts = [UserDefinedContextConfig(content="shared background")]
    parent.starters = ["deprecated starter"]
    parent.conversation_starters = ConversationStartersConfig(
        starters=[ConversationStarter(title="Go", text="do the thing")]
    )

    manifest = compile_subagent_manifest(parent, RESEARCHER)

    assert manifest.orchestrator.system_prompt.content == RESEARCHER.system_prompt
    assert manifest.orchestrator.max_iterations == 3
    assert [ts.name for ts in manifest.tool_sets] == ["research"]
    assert manifest.features is not None
    assert manifest.features.subagents is None, "a spoke must not be able to spawn"
    # Coordinator↔user conversation UI is cleared: a spoke has no user to seed.
    assert manifest.starters is None
    assert manifest.conversation_starters is None
    # contexts (and skills / hooks / other features) are inherited wholesale —
    # deep-copied, so equal by value but a distinct object from the parent's.
    assert manifest.contexts == parent.contexts
    assert manifest.contexts is not parent.contexts
    # The coordinator's own manifest is untouched.
    assert [ts.name for ts in parent.tool_sets] == ["research", "reporting"]
    assert parent.orchestrator.system_prompt.content == "test"
    assert parent.starters == ["deprecated starter"]
    assert parent.conversation_starters is not None


def test_a_general_purpose_spoke_gets_only_the_tool_sets_the_spawn_asked_for():
    """The core of the general-purpose design: tools are scoped per call, never inherited."""
    parent = _parent_config()

    manifest = compile_subagent_manifest(
        parent, general_purpose_subagent(GENERAL_PURPOSE, ["reporting"])
    )

    assert [ts.name for ts in manifest.tool_sets] == ["reporting"]
    assert manifest.orchestrator.system_prompt.content == GENERAL_PURPOSE_SYSTEM_PROMPT


def test_an_empty_request_yields_a_toolless_general_purpose_spoke():
    """`[]` is a deliberate reasoning-only subagent, not a mistake to correct."""
    manifest = compile_subagent_manifest(
        _parent_config(), general_purpose_subagent(GENERAL_PURPOSE, [])
    )

    assert manifest.tool_sets == []


def test_general_purpose_overrides_replace_the_defaults():
    tuned = GeneralPurposeSubagentConfig(
        system_prompt="Be terse.", deployment_id="gpt-4.1-2025-04-14", max_iterations=3
    )

    manifest = compile_subagent_manifest(
        _parent_config(), general_purpose_subagent(tuned, ["research"])
    )

    assert manifest.orchestrator.system_prompt.content == "Be terse."
    assert manifest.orchestrator.deployment.deployment_id == "gpt-4.1-2025-04-14"
    assert manifest.orchestrator.max_iterations == 3


def test_unset_overrides_inherit_the_coordinator_model_and_budget():
    parent = _parent_config()

    manifest = compile_subagent_manifest(
        parent, general_purpose_subagent(GENERAL_PURPOSE, ["research"])
    )

    assert (
        manifest.orchestrator.deployment.deployment_id
        == parent.orchestrator.deployment.deployment_id
    )
    assert manifest.orchestrator.max_iterations == parent.orchestrator.max_iterations


def test_unresolvable_tool_sets_fail_the_spawn():
    """A subagent that asked for tools and got none must not run: it would answer
    from the task text alone and sound confident doing it."""
    parent = _parent_config()
    dangling = RESEARCHER.model_copy(update={"tool_sets": ["Fetch MCP toolset"]})

    with pytest.raises(SubagentToolSetResolutionError) as excinfo:
        compile_subagent_manifest(parent, dangling)

    assert "Fetch MCP toolset" in str(excinfo.value)
    assert "research" in str(excinfo.value)


def test_empty_declared_tool_sets_is_allowed():
    """An explicitly empty allowlist is a deliberate no-tools subagent, not a typo."""
    parent = _parent_config()
    toolless = RESEARCHER.model_copy(update={"tool_sets": []})

    manifest = compile_subagent_manifest(parent, toolless)

    assert manifest.tool_sets == []


# --- the `task` tool --------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_tool_offers_declared_types_and_the_general_purpose_subagent(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

    config = _parent_config()
    config.tool_sets[0].description = "Digs through sources."

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, config)
        await invoke_initializers(injector, InitializerType.completion)
        tool = _spawn_tool(injector)

    assert tool is not None
    function = tool.tool_config.open_ai_tool.function
    properties = function.parameters.properties
    assert sorted(properties) == ["prompt", "subagent_type", "tool_sets"]
    assert function.parameters.required == ["subagent_type", "prompt"]
    assert properties["subagent_type"].enum == [GENERAL_PURPOSE_SUBAGENT_NAME, "researcher"]
    assert "researcher: Digs through sources" in function.description
    assert f"{GENERAL_PURPOSE_SUBAGENT_NAME}: General-purpose" in function.description
    assert properties["tool_sets"].items.enum == ["research", "reporting"]
    # The catalogue: the coordinator knows its tools but not which set holds them.
    assert "- research: Digs through sources." in properties["tool_sets"].description
    assert "- reporting" in properties["tool_sets"].description


@pytest.mark.asyncio
async def test_spawn_tool_without_general_purpose_offers_no_tool_sets_argument(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

    config = _parent_config(SubagentsConfig(enabled=True, general_purpose=None, types=[RESEARCHER]))

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, config)
        await invoke_initializers(injector, InitializerType.completion)
        tool = _spawn_tool(injector)

    assert tool is not None
    properties = tool.tool_config.open_ai_tool.function.parameters.properties
    assert sorted(properties) == ["prompt", "subagent_type"]
    assert properties["subagent_type"].enum == ["researcher"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "subagents",
    [
        None,
        SubagentsConfig(enabled=False, types=[RESEARCHER]),
        SubagentsConfig(enabled=True, general_purpose=None),
    ],
    ids=["absent", "disabled", "nothing to spawn"],
)
async def test_no_spawn_tool_unless_a_subagent_is_offered(monkeypatch, subagents):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

    config = create_app_configuration([])
    assert config.features is not None
    config.features.subagents = subagents

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, config)
        await invoke_initializers(injector, InitializerType.completion)

        assert _spawn_tool(injector) is None


@pytest.mark.asyncio
async def test_disabled_tool_sets_are_not_selectable(monkeypatch):
    """A disabled set produces no tools, so offering it would only invite an empty spoke."""
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

    config = _parent_config()
    config.tool_sets[1].enabled = False

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, config)
        await invoke_initializers(injector, InitializerType.completion)
        tool = _spawn_tool(injector)

        assert tool is not None
        assert tool.tool_config.open_ai_tool.function.parameters.properties[
            "tool_sets"
        ].items.enum == ["research"]

        with pytest.raises(InvalidToolCallParameterException):
            await tool._run_in_stage_async(
                subagent_type=GENERAL_PURPOSE_SUBAGENT_NAME,
                prompt="Report.",
                tool_sets=["reporting"],
            )


@pytest.mark.asyncio
async def test_an_unknown_tool_set_fails_the_call_without_spawning(monkeypatch):
    """Dropping the bad name instead would run a spoke with fewer tools than intended,
    which does not error — it answers from the prompt alone."""
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
    _FakeOrchestrator.seen = []

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, _parent_config())
        await invoke_initializers(injector, InitializerType.completion)
        tool = _spawn_tool(injector)
        assert tool is not None

        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await tool._run_in_stage_async(
                subagent_type=GENERAL_PURPOSE_SUBAGENT_NAME,
                prompt="Dig in.",
                tool_sets=["Fetch MCP toolset"],
            )

    assert "Fetch MCP toolset" in str(excinfo.value)
    assert "research" in str(excinfo.value)
    assert _FakeOrchestrator.seen == []


@pytest.mark.asyncio
async def test_omitting_tool_sets_fails_a_general_purpose_call(monkeypatch):
    """Required, so that a tool-less spoke is always a deliberate choice."""
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, _parent_config())
        await invoke_initializers(injector, InitializerType.completion)
        tool = _spawn_tool(injector)
        assert tool is not None

        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await tool._run_in_stage_async(
                subagent_type=GENERAL_PURPOSE_SUBAGENT_NAME, prompt="Dig in."
            )

    assert excinfo.value.parameter_name == "tool_sets"


@pytest.mark.asyncio
async def test_tool_sets_on_a_declared_type_fails_the_call(monkeypatch):
    """A declared type's allowlist is the builder's; silently ignoring the argument
    would let the coordinator believe it narrowed a spoke it did not."""
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
    _FakeOrchestrator.seen = []

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, _parent_config())
        await invoke_initializers(injector, InitializerType.completion)
        tool = _spawn_tool(injector)
        assert tool is not None

        with pytest.raises(InvalidToolCallParameterException, match="fixed tool set"):
            await tool._run_in_stage_async(
                subagent_type="researcher", prompt="Dig in.", tool_sets=["research"]
            )

    assert _FakeOrchestrator.seen == []


@pytest.mark.asyncio
async def test_an_unknown_subagent_type_fails_the_call(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, _parent_config())
        await invoke_initializers(injector, InitializerType.completion)
        tool = _spawn_tool(injector)
        assert tool is not None

        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await tool._run_in_stage_async(subagent_type="plumber", prompt="Fix it.")

    assert "researcher" in str(excinfo.value)
    assert GENERAL_PURPOSE_SUBAGENT_NAME in str(excinfo.value)


@pytest.mark.asyncio
async def test_the_general_purpose_name_is_unknown_once_switched_off(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

    config = _parent_config(SubagentsConfig(enabled=True, general_purpose=None, types=[RESEARCHER]))

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, config)
        await invoke_initializers(injector, InitializerType.completion)
        tool = _spawn_tool(injector)
        assert tool is not None

        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await tool._run_in_stage_async(
                subagent_type=GENERAL_PURPOSE_SUBAGENT_NAME, prompt="Dig in.", tool_sets=[]
            )

    assert excinfo.value.parameter_name == "subagent_type"


@pytest.mark.asyncio
async def test_dangling_tool_set_reference_is_reported_at_initialization(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

    config = _parent_config(
        SubagentsConfig(
            enabled=True,
            types=[RESEARCHER.model_copy(update={"tool_sets": ["Fetch MCP toolset"]})],
        )
    )

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, config)
        await invoke_initializers(injector, InitializerType.completion)

        exceptions = injector.get(list[InitializationException])

        messages = [str(e) for e in exceptions]
        assert any("Fetch MCP toolset" in m and "researcher" in m for m in messages), messages


# --- spawning ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_runs_in_an_isolated_request_scope(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
    _FakeOrchestrator.seen = []

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)
    parent_config = _parent_config()

    async with scope_factory.create_scope():  # the coordinator's request
        parent_context = await _enter_coordinator_scope(injector, parent_config)

        spawner = injector.get(SubagentSpawner)
        spawned = await spawner.spawn(RESEARCHER, "Find out who broke the build.")

        # The spoke returned only its final answer.
        assert spawned.answer == "42 sources, one answer."

        # The spoke ran against the compiled manifest, not the coordinator's.
        assert len(_FakeOrchestrator.seen) == 1
        child_config = _FakeOrchestrator.seen[0]
        assert child_config is not parent_config
        assert [ts.name for ts in child_config.tool_sets] == ["research"]
        assert child_config.orchestrator.system_prompt.content == RESEARCHER.system_prompt

        # The coordinator's scope is untouched: same context object, same manifest,
        # and none of the spoke's messages leaked in.
        assert injector.get(_RequestContext) is parent_context
        assert parent_context.application_config is parent_config
        assert [m.content for m in parent_context.messages] == ["do the thing"]


@pytest.mark.asyncio
async def test_a_general_purpose_spawn_runs_with_the_tool_sets_the_call_named(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
    _FakeOrchestrator.seen = []

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, _parent_config())
        await invoke_initializers(injector, InitializerType.completion)
        tool = _spawn_tool(injector)
        assert tool is not None

        result = await tool._run_in_stage_async(
            subagent_type=GENERAL_PURPOSE_SUBAGENT_NAME,
            prompt="Write it up.",
            tool_sets=["reporting"],
        )

    assert result.content == "42 sources, one answer."
    assert len(_FakeOrchestrator.seen) == 1
    child_config = _FakeOrchestrator.seen[0]
    assert [ts.name for ts in child_config.tool_sets] == ["reporting"]
    assert child_config.orchestrator.system_prompt.content == GENERAL_PURPOSE_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_parallel_spawns_do_not_share_scope(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
    _FakeOrchestrator.seen = []

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, _parent_config())

        spawner = injector.get(SubagentSpawner)
        await asyncio.gather(
            spawner.spawn(RESEARCHER, "task one"),
            spawner.spawn(general_purpose_subagent(GENERAL_PURPOSE, ["reporting"]), "task two"),
        )

    assert len(_FakeOrchestrator.seen) == 2
    tool_sets = sorted(ts.name for config in _FakeOrchestrator.seen for ts in config.tool_sets)
    assert tool_sets == ["reporting", "research"]


class _SilentOrchestrator:
    """A spoke that ends its run without a final assistant message.

    This is what exhausting ``max_iterations`` mid-tool-loop leaves behind.
    """

    @inject
    def __init__(self) -> None:
        pass

    async def invoke(self) -> None:
        return


@pytest.mark.asyncio
async def test_spawn_without_a_final_answer_fails_the_tool_call(monkeypatch):
    """An answerless spoke must surface as a tool error, not an empty success.

    Returning "" would reach the coordinator's LLM as a successful result, and it
    would then answer from nothing.
    """
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

    injector = _test_injector()
    injector.binder.bind(Orchestrator, to=_SilentOrchestrator)  # type: ignore[type-abstract,arg-type]
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, _parent_config())
        spawner = injector.get(SubagentSpawner)

        with pytest.raises(SubagentToolErrorException) as excinfo:
            await spawner.spawn(RESEARCHER, "Find out who broke the build.")

    assert "max_iterations" in excinfo.value.user_facing_message
    assert "researcher" in excinfo.value.user_facing_message


class _SlowOrchestrator:
    """A spoke that never finishes within any sane budget."""

    @inject
    def __init__(self) -> None:
        pass

    async def invoke(self) -> None:
        await asyncio.sleep(30)


@pytest.mark.asyncio
async def test_spawn_exceeding_its_budget_fails_the_tool_call(monkeypatch):
    """A truncated spoke has no answer, so it must surface as an actionable error."""
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

    config = _parent_config(SubagentsConfig(enabled=True, types=[RESEARCHER], timeout_seconds=0.05))

    injector = _test_injector()
    injector.binder.bind(Orchestrator, to=_SlowOrchestrator)  # type: ignore[type-abstract,arg-type]
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, config)
        spawner = injector.get(SubagentSpawner)

        with pytest.raises(SubagentToolErrorException) as excinfo:
            await spawner.spawn(RESEARCHER, "Take your time.")

    assert "0.05s budget" in excinfo.value.user_facing_message


def test_an_app_may_shorten_the_admin_ceiling_but_not_extend_it():
    spawner = SubagentSpawner.__new__(SubagentSpawner)
    spawner._SubagentSpawner__settings = SubagentSettings(  # type: ignore[attr-defined]
        SUBAGENT_TIMEOUT_SECONDS=60
    )
    resolve = spawner._SubagentSpawner__timeout  # type: ignore[attr-defined]

    for declared, expected in ((None, 60), (10, 10), (600, 60)):
        spawner._SubagentSpawner__config = SubagentsConfig(  # type: ignore[attr-defined]
            enabled=True, timeout_seconds=declared
        )
        assert resolve() == expected


class _ConcurrencyProbe:
    """Records how many spokes were inside the orchestrator loop at once."""

    live = 0
    peak = 0

    @inject
    def __init__(self, messages: MessagesMixin) -> None:
        self._messages = messages

    async def invoke(self) -> None:
        type(self).live += 1
        type(self).peak = max(type(self).peak, type(self).live)
        try:
            await asyncio.sleep(0.01)
            self._messages.append_message(Message(role=Role.ASSISTANT, content="done"))
        finally:
            type(self).live -= 1


@pytest.mark.asyncio
async def test_parallel_spawns_are_capped(monkeypatch):
    """Fan-out is encouraged, so something has to bound what one decision can start."""
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
    monkeypatch.setenv("SUBAGENT_MAX_CONCURRENT_SPAWNS", "2")
    _ConcurrencyProbe.live = 0
    _ConcurrencyProbe.peak = 0

    injector = _test_injector()
    injector.binder.bind(Orchestrator, to=_ConcurrencyProbe)  # type: ignore[type-abstract,arg-type]
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, _parent_config())
        spawner = injector.get(SubagentSpawner)

        results = await asyncio.gather(*(spawner.spawn(RESEARCHER, f"task {i}") for i in range(6)))

    # Every spawn still completed — excess ones queue rather than fail.
    assert [r.answer for r in results] == ["done"] * 6
    assert _ConcurrencyProbe.peak == 2


class _PlottingOrchestrator:
    """A spoke that produces a file, not just prose."""

    @inject
    def __init__(self, messages: MessagesMixin, choice: Choice) -> None:
        self._messages = messages
        self._choice = choice

    async def invoke(self) -> None:
        self._choice.add_attachment(type="image/png", title="chart", url="files/x/chart.png")
        self._messages.append_message(Message(role=Role.ASSISTANT, content="Chart attached."))


@pytest.mark.asyncio
async def test_a_spoke_can_return_a_file_to_the_coordinator(monkeypatch):
    """A spoke's chart has to cross back, or delegating plotting work is pointless."""
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

    injector = _test_injector()
    injector.binder.bind(Orchestrator, to=_PlottingOrchestrator)  # type: ignore[type-abstract,arg-type]
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, _parent_config())
        spawner = injector.get(SubagentSpawner)

        spawned = await spawner.spawn(RESEARCHER, "Plot the results.")

    assert spawned.answer == "Chart attached."
    assert [a.url for a in spawned.attachments] == ["files/x/chart.png"]


class _RecordingErrorHandler:
    """Stands in for the initialization-issues stage; records what each scope saw."""

    seen: list[int] = []

    @inject
    def __init__(self, exceptions: ProviderOf[list[InitializationException]]) -> None:
        # Lazy, like the real handler: the list depends on the resolved config.
        self.__exceptions = exceptions

    def handle_initialization_issues(self) -> None:
        type(self).seen.append(len(self.__exceptions.get()))


@pytest.mark.asyncio
async def test_spoke_initialization_issues_reach_the_handler(monkeypatch):
    """A spoke runs the same initialization-issues check a user request does.

    Before the lifecycle was shared, a spoke whose tools failed to initialize ran
    silently with whatever was left.
    """
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
    _FakeOrchestrator.seen = []
    _RecordingErrorHandler.seen = []

    injector = _test_injector()
    injector.binder.bind(
        _InitializationErrorHandler, to=_RecordingErrorHandler  # type: ignore[arg-type]
    )
    injector.binder.multibind(
        list[InitializationException],
        to=[ToolInitializationException(message="tool is down", tool_name="broken")],
    )
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        await _enter_coordinator_scope(injector, _parent_config())

        spawned = await injector.get(SubagentSpawner).spawn(RESEARCHER, "Find out.")

    assert spawned.answer == "42 sources, one answer."
    # Exactly one check ran — in the spoke's scope — and it saw the failed tool.
    assert _RecordingErrorHandler.seen == [1]
