"""DI wiring for ``SkillInvocationModule`` — an ordinary provider, initializer and
transformer, registered in ``app_factory``."""

from unittest.mock import MagicMock

from fastapi_injector import Injected, request_scope
from injector import Binder, Module, multiprovider
from starlette.testclient import TestClient

from quickapp.common import REQUEST_MESSAGES, StagedBaseTool
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.skills.invocation import SkillInvocationModule
from quickapp.skills.skill_resolver import DialSkillResourceResolver
from quickapp.skills.skills_provider import SkillsProvider
from tests.unit_tests.common.common import create_test_app


class _StubDependenciesModule(Module):
    """Binds what the module takes from the rest of the app."""

    def configure(self, binder: Binder) -> None:
        binder.bind(
            DialSkillResourceResolver,
            to=lambda: MagicMock(spec=DialSkillResourceResolver),
            scope=request_scope,
        )

    @multiprovider
    def _provide_request_messages(self) -> REQUEST_MESSAGES:
        return []

    @multiprovider
    def _provide_tools(self) -> list[StagedBaseTool]:
        return []


def _make_client() -> TestClient:
    app = create_test_app([_StubDependenciesModule(), SkillInvocationModule()])

    @app.get("/types")
    async def types(
        providers: list[SkillsProvider] = Injected(list[SkillsProvider]),
        initializers: list[CompletionInitializer] = Injected(list[CompletionInitializer]),
        transformers: list[MessagesTransformer] = Injected(list[MessagesTransformer]),
    ) -> dict[str, list[str]]:
        return {
            "providers": [type(p).__name__ for p in providers],
            "initializers": [type(i).__name__ for i in initializers],
            "transformers": [type(t).__name__ for t in transformers],
        }

    return TestClient(app)


class TestWiring:

    def test_the_module_contributes_a_provider_an_initializer_and_a_transformer(self):
        body = _make_client().get("/types").json()

        assert body["providers"] == ["_InvokedSkillsContext"]
        assert body["initializers"] == ["_SkillInvocationInitializer"]
        assert body["transformers"] == ["_SkillInvocationInjector"]
