"""SPIKE validation for Approach A (in-process subagents).

These tests exist to answer one question: can a spawned subagent run its own
orchestrator loop, against its own manifest, in a DI request scope that is fully
isolated from the coordinator's — without touching the coordinator's state?
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Message, Role
from fastapi_injector import RequestScopeFactory
from injector import Binder, Injector, inject
from pydantic import SecretStr

from quickapp.common import StagedBaseTool
from quickapp.common.base_initializer import InitializerType, invoke_initializers
from quickapp.common.exceptions import InitializationException
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.config.application import ApplicationConfig
from quickapp.config.context import UserDefinedContextConfig
from quickapp.config.starters import ConversationStarter, ConversationStartersConfig
from quickapp.config.subagent import SubagentConfig
from quickapp.config.toolsets.internal import InternalToolSet
from quickapp.core.agent.orchestrator import Orchestrator
from quickapp.core.application._request_context import _RequestContext
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService
from quickapp.subagent_tooling._exceptions import (
    SubagentToolErrorException,
    SubagentToolSetResolutionError,
)
from quickapp.subagent_tooling._manifest_compiler import compile_subagent_manifest
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


def _parent_config() -> ApplicationConfig:
    config = create_app_configuration(
        [
            InternalToolSet(name="research", tools=[]),
            InternalToolSet(name="reporting", tools=[]),
        ]
    )
    config.subagents = [RESEARCHER]
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
    assert manifest.subagents is None, "a spoke must not be able to spawn"
    # Coordinator↔user conversation UI is cleared: a spoke has no user to seed.
    assert manifest.starters is None
    assert manifest.conversation_starters is None
    # contexts (and skills / hooks / features) are inherited wholesale — deep-copied,
    # so equal by value but a distinct object from the parent's.
    assert manifest.contexts == parent.contexts
    assert manifest.contexts is not parent.contexts
    # The coordinator's own manifest is untouched.
    assert [ts.name for ts in parent.tool_sets] == ["research", "reporting"]
    assert parent.orchestrator.system_prompt.content == "test"
    assert parent.starters == ["deprecated starter"]
    assert parent.conversation_starters is not None


@pytest.mark.asyncio
async def test_spawn_runs_in_an_isolated_request_scope(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
    _FakeOrchestrator.seen = []

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)
    parent_config = _parent_config()

    async with scope_factory.create_scope():  # the coordinator's request
        parent_context = injector.get(_RequestContext)
        parent_context.api_key = SecretStr("key")
        parent_context.bearer = None
        parent_context.forwarded_headers = {}
        parent_context.application_config = parent_config
        parent_context.messages = [Message(role=Role.USER, content="do the thing")]

        spawner = injector.get(SubagentSpawner)
        answer = await spawner.spawn(RESEARCHER, "Find out who broke the build.")

        # The spoke returned only its final answer.
        assert answer == "42 sources, one answer."

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
async def test_spawn_tool_is_offered_to_the_coordinator(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        context = injector.get(_RequestContext)
        context.api_key = SecretStr("key")
        context.bearer = None
        context.forwarded_headers = {}
        context.application_config = _parent_config()
        context.messages = [Message(role=Role.USER, content="do the thing")]
        await invoke_initializers(injector, InitializerType.completion)

        tools = injector.get(list[StagedBaseTool])
        spawn_tools = [t for t in tools if t.openai_function_name() == TASK_TOOL_NAME]

        assert len(spawn_tools) == 1
        function = spawn_tools[0].tool_config.open_ai_tool.function
        assert function.parameters.properties["subagent_type"].enum == ["researcher"]
        assert "researcher: Digs through sources" in function.description


@pytest.mark.asyncio
async def test_no_spawn_tool_without_declared_subagents(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        context = injector.get(_RequestContext)
        context.api_key = SecretStr("key")
        context.bearer = None
        context.forwarded_headers = {}
        context.application_config = create_app_configuration([])
        context.messages = [Message(role=Role.USER, content="do the thing")]
        await invoke_initializers(injector, InitializerType.completion)

        tools = injector.get(list[StagedBaseTool])

        assert [t for t in tools if t.openai_function_name() == TASK_TOOL_NAME] == []


@pytest.mark.asyncio
async def test_parallel_spawns_do_not_share_scope(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
    _FakeOrchestrator.seen = []

    other = RESEARCHER.model_copy(update={"name": "reporter", "tool_sets": ["reporting"]})
    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        context = injector.get(_RequestContext)
        context.api_key = SecretStr("key")
        context.bearer = None
        context.forwarded_headers = {}
        context.application_config = _parent_config()
        context.messages = [Message(role=Role.USER, content="do the thing")]

        spawner = injector.get(SubagentSpawner)
        await asyncio.gather(
            spawner.spawn(RESEARCHER, "task one"),
            spawner.spawn(other, "task two"),
        )

    assert len(_FakeOrchestrator.seen) == 2
    tool_sets = sorted(ts.name for config in _FakeOrchestrator.seen for ts in config.tool_sets)
    assert tool_sets == ["reporting", "research"]


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


@pytest.mark.asyncio
async def test_dangling_tool_set_reference_is_reported_at_initialization(monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

    config = _parent_config()
    config.subagents = [RESEARCHER.model_copy(update={"tool_sets": ["Fetch MCP toolset"]})]

    injector = _test_injector()
    scope_factory = injector.get(RequestScopeFactory)

    async with scope_factory.create_scope():
        context = injector.get(_RequestContext)
        context.api_key = SecretStr("key")
        context.bearer = None
        context.forwarded_headers = {}
        context.application_config = config
        context.messages = [Message(role=Role.USER, content="do the thing")]
        await invoke_initializers(injector, InitializerType.completion)

        exceptions = injector.get(list[InitializationException])

        messages = [str(e) for e in exceptions]
        assert any("Fetch MCP toolset" in m and "researcher" in m for m in messages), messages


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
        context = injector.get(_RequestContext)
        context.api_key = SecretStr("key")
        context.bearer = None
        context.forwarded_headers = {}
        context.application_config = _parent_config()
        context.messages = [Message(role=Role.USER, content="do the thing")]

        spawner = injector.get(SubagentSpawner)

        with pytest.raises(SubagentToolErrorException) as excinfo:
            await spawner.spawn(RESEARCHER, "Find out who broke the build.")

    assert "max_iterations" in excinfo.value.user_facing_message
    assert "researcher" in excinfo.value.user_facing_message
