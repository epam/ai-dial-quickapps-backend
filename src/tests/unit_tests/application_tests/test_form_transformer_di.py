"""DI smoke test: the full AppFactory module set resolves ``list[MessagesTransformer]``
in a request scope, with ``_FormValueContentTransformer`` first in the chain."""

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi_injector import InjectorMiddleware, RequestScopeOptions, attach_injector
from injector import Injector
from pydantic import SecretStr
from starlette.testclient import TestClient

from quickapp.app_factory import AppFactory
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.dial_settings import DialSettings
from quickapp.config.application import ApplicationConfig
from quickapp.core.agent._form_value_content_transformer import _FormValueContentTransformer
from quickapp.core.agent.orchestrator_capabilities import OrchestratorCapabilities
from quickapp.core.application._request_context import _RequestContext
from tests.unit_tests.common.common import create_app_configuration


def _make_full_app() -> tuple[FastAPI, Injector]:
    app = FastAPI()

    def configure(binder):
        binder.bind(ApplicationConfig, to=create_app_configuration([]))
        binder.bind(DialSettings, to=DialSettings(url="https://dial.local"))
        caps = MagicMock(spec=OrchestratorCapabilities)
        caps.input_attachment_types = []
        caps.deployment_id = "test-model"
        binder.bind(OrchestratorCapabilities, to=caps)

    injector = Injector(AppFactory.build_di_modules() + [configure])
    app.add_middleware(InjectorMiddleware, injector=injector)
    attach_injector(app, injector, RequestScopeOptions())
    return app, injector


def test_form_value_transformer_resolved_first_in_request_scope():
    app, injector = _make_full_app()

    @app.get("/ping")
    def ping():
        ctx = injector.get(_RequestContext)
        ctx.api_key = SecretStr("test")
        ctx.bearer = SecretStr("test")
        ctx.messages = []
        transformers = injector.get(list[MessagesTransformer])
        return {"first": type(transformers[0]).__name__, "count": len(transformers)}

    with TestClient(app) as client:
        response = client.get("/ping")

    assert response.status_code == 200
    assert response.json()["first"] == _FormValueContentTransformer.__name__
