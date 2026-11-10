"""DI wiring for the orchestrator initializers ``AgentModule`` contributes."""

from unittest.mock import MagicMock

from fastapi_injector import Injected, request_scope
from injector import Binder, Module
from starlette.testclient import TestClient

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.config.application import ApplicationConfig
from quickapp.core.agent.agent_module import AgentModule
from quickapp.dial_core_services.dial_prompt_loader import DialPromptLoader
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService
from tests.unit_tests.common.common import create_app_configuration, create_test_app


class _StubDependenciesModule(Module):
    """Binds what the initializers take from the rest of the app."""

    def configure(self, binder: Binder) -> None:
        binder.bind(ApplicationConfig, to=lambda: create_app_configuration([]), scope=request_scope)
        binder.bind(
            ToolConfigCoreService,
            to=lambda: MagicMock(spec=ToolConfigCoreService),
            scope=request_scope,
        )
        binder.bind(
            DialPromptLoader, to=lambda: MagicMock(spec=DialPromptLoader), scope=request_scope
        )


def test_module_contributes_both_orchestrator_initializers():
    app = create_test_app([_StubDependenciesModule(), AgentModule()])

    @app.get("/initializers")
    async def initializers(
        resolved: list[CompletionInitializer] = Injected(list[CompletionInitializer]),
    ) -> list[str]:
        return [type(i).__name__ for i in resolved]

    assert TestClient(app).get("/initializers").json() == [
        "_OrchestratorDeploymentInitializer",
        "_DialSystemPromptInitializer",
    ]
