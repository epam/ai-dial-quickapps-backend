"""DI wiring for ``SkillInvocationModule`` — an ordinary provider, initializer and
transformer, registered in ``app_factory`` behind the preview flag."""

from unittest.mock import MagicMock, patch

from fastapi_injector import Injected, request_scope
from injector import Binder, Module, multiprovider
from starlette.testclient import TestClient

from quickapp.app_factory import AppFactory
from quickapp.common import REQUEST_MESSAGES, StagedBaseTool
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.skills.dial._dial_skill_resolver import DialSkillResolver
from quickapp.skills.invocation import SkillInvocationModule
from quickapp.skills.skills_provider import SkillsProvider
from tests.unit_tests.common.common import create_test_app


class _StubDependenciesModule(Module):
    """Binds what the module takes from the rest of the app."""

    def configure(self, binder: Binder) -> None:
        binder.bind(
            DialSkillResolver, to=lambda: MagicMock(spec=DialSkillResolver), scope=request_scope
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


class TestRegistration:

    def test_registered_when_preview_features_are_on(self):
        with patch.dict("os.environ", {"ENABLE_PREVIEW_FEATURES": "true"}):
            names = [type(m).__name__ for m in AppFactory.build_di_modules()]
        assert "SkillInvocationModule" in names

    def test_dropped_when_preview_features_are_off(self):
        with patch.dict("os.environ", {"ENABLE_PREVIEW_FEATURES": "false"}):
            names = [type(m).__name__ for m in AppFactory.build_di_modules()]
        assert "SkillInvocationModule" not in names
        # The chips are still scrubbed: _ScrubExtraFieldsTransformer lives in the never-gated
        # AgentModule.
        assert "AgentModule" in names
