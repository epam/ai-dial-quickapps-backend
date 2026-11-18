from aidial_sdk.chat_completion import CustomContent, Message, Role
from fastapi_injector import Injected
from injector import Binder
from starlette.testclient import TestClient

from quickapp.common import REQUEST_MESSAGES
from quickapp.common.deferred_tool_types import DeferredToolDefinition
from quickapp.common.state_holder import StateHolder
from quickapp.core.agent.agent_module import AgentModule
from quickapp.core.agent.lazy_loaded_tools_holder import (
    DISCOVERED_TOOLS_STATE_KEY,
    LazyLoadedToolsHolder,
)
from tests.unit_tests.common.common import create_test_app, make_tools_holder


def _definition(name: str) -> DeferredToolDefinition:
    return DeferredToolDefinition(
        name=name, definition={"type": "function", "function": {"name": name}}
    )


def _assistant(state: dict | None) -> Message:
    return Message(
        role=Role.ASSISTANT,
        content="ok",
        custom_content=CustomContent(state=state) if state is not None else None,
    )


def _assistant_with_discovered(names: list[str]) -> Message:
    return _assistant({DISCOVERED_TOOLS_STATE_KEY: names})


def _provide_holder(
    definitions: list[DeferredToolDefinition],
    messages: list[Message],
    state_holder: StateHolder,
) -> LazyLoadedToolsHolder:
    return make_tools_holder(state_holder, messages, definitions)


class TestRestore:
    def test_restores_tools_in_discovery_order_and_drops_stale_names(self):
        state_holder = StateHolder()

        holder = _provide_holder(
            [_definition("a"), _definition("b"), _definition("c")],
            [_assistant_with_discovered(["c", "gone", "a"])],
            state_holder,
        )

        assert holder.names == ["c", "a"]
        assert state_holder.get_state() == {DISCOVERED_TOOLS_STATE_KEY: ["c", "a"]}

    def test_writes_nothing_on_a_conversation_without_discovery(self):
        state_holder = StateHolder()

        holder = _provide_holder(
            [_definition("a")], [Message(role=Role.USER, content="hi")], state_holder
        )

        assert holder.names == []
        assert state_holder.get_state() == {}

    def test_persists_empty_list_when_every_restored_name_is_stale(self):
        state_holder = StateHolder()

        holder = _provide_holder([], [_assistant_with_discovered(["gone"])], state_holder)

        assert holder.names == []
        assert state_holder.get_state() == {DISCOVERED_TOOLS_STATE_KEY: []}

    def test_newly_discovered_tools_extend_the_persisted_names(self):
        state_holder = StateHolder()
        holder = _provide_holder(
            [_definition("a"), _definition("b")], [_assistant_with_discovered(["a"])], state_holder
        )

        holder.add([_definition("b").definition])

        assert state_holder.get_state() == {DISCOVERED_TOOLS_STATE_KEY: ["a", "b"]}

    def test_reads_definitions_on_first_use_not_on_creation(self):
        # REST and internal tools register their deferred definitions while the tool list is
        # built, which may happen after the holder is created.
        definitions: list[DeferredToolDefinition] = []
        holder = _provide_holder(definitions, [_assistant_with_discovered(["a"])], StateHolder())

        definitions.append(_definition("a"))

        assert holder.names == ["a"]


class TestReadStoredNames:
    @staticmethod
    def _names(messages: list[Message]) -> list[str]:
        defs = [_definition(n) for n in ("a", "b")]
        return _provide_holder(defs, messages, StateHolder()).names

    def test_returns_names_from_latest_assistant_message_with_the_key(self) -> None:
        messages = [
            _assistant_with_discovered(["a"]),
            Message(role=Role.USER, content="next"),
            _assistant_with_discovered(["a", "b"]),
            Message(role=Role.USER, content="again"),
        ]

        assert self._names(messages) == ["a", "b"]

    def test_ignores_messages_without_the_key(self) -> None:
        messages = [
            _assistant_with_discovered(["a"]),
            _assistant({"other": 1}),
            _assistant(None),
        ]

        assert self._names(messages) == ["a"]

    def test_empty_list_in_latest_message_is_authoritative(self) -> None:
        messages = [_assistant_with_discovered(["a"]), _assistant_with_discovered([])]

        assert self._names(messages) == []

    def test_malformed_value_yields_nothing(self) -> None:
        assert self._names([_assistant({DISCOVERED_TOOLS_STATE_KEY: "a"})]) == []
        assert self._names([_assistant({DISCOVERED_TOOLS_STATE_KEY: ["a", 1, ""]})]) == ["a"]

    def test_no_assistant_messages(self) -> None:
        assert self._names([Message(role=Role.USER, content="hi")]) == []


class TestHolderSharing:
    def test_agent_module_binds_one_holder_per_request_without_tool_discovery(self):
        def configure(binder: Binder) -> None:
            binder.multibind(list[DeferredToolDefinition], to=[])
            binder.multibind(REQUEST_MESSAGES, to=[])

        app = create_test_app([AgentModule(), configure])
        seen: list[LazyLoadedToolsHolder] = []

        @app.get("/holders")
        async def holders(
            first: LazyLoadedToolsHolder = Injected(LazyLoadedToolsHolder),
            second: LazyLoadedToolsHolder = Injected(LazyLoadedToolsHolder),
        ) -> None:
            seen.extend([first, second])

        TestClient(app).get("/holders")
        TestClient(app).get("/holders")

        assert seen[0] is seen[1]
        assert seen[2] is seen[3]
        assert seen[0] is not seen[2]
