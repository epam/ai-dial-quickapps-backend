from injector import provider, Injector, singleton
from fastapi_injector import request_scope

from fastapi import FastAPI

from quickapp.agent.agent_module import AgentModule
from quickapp.application import AppModule
from quickapp.attachment_processing.attachment_processing_module import AttachmentProcessingModule
from quickapp.common import DIAL_API_KEY
from quickapp.common.dial_settings import DialSettings
from quickapp.dial_core_services.dial_core_services_module import DialCoreServicesModule
from quickapp.dial_deployment_tooling import DialDeploymentToolingModule
from quickapp.file_transfer import FileTransferModule
from quickapp.mcp_tooling import MCPToolingModule
from quickapp.internal_tooling.internal_tooling_module import InternalToolModule
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_client import (
    _PyInterpreterClient,
)
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_settings import (
    _PyInterpreterSettings,
    _PY_INTERPRETER_API_KEY,
)
from quickapp.rest_api_tooling import RestApiToolingModule
from quickapp.skills.skills_module import SkillsModule
from quickapp.timestamp_tooling.timestamp_module import TimestampModule
from tests.integration_tests.test_runner.config import TestConfig


class PyInterpreterTestModule(InternalToolModule):
    @request_scope
    @provider
    def _provide_py_interpreter_client(
        self, api_key: DIAL_API_KEY, py_interpreter_settings: _PyInterpreterSettings
    ) -> _PyInterpreterClient:
        return _PyInterpreterClient(
            api_key=TestConfig.PY_INTERPRETER_API_KEY,
            base_url=TestConfig.PY_INTERPRETER_URL,
            timeout=py_interpreter_settings.client_timeout,
            max_retries=py_interpreter_settings.client_max_retries,
        )

    @singleton
    @provider
    def _provide_py_interpreter_settings(
        self, dial_settings: DialSettings
    ) -> _PyInterpreterSettings:
        py_interpreter_settings = _PyInterpreterSettings()
        if not py_interpreter_settings.url:
            py_interpreter_settings.url = dial_settings.url
        return py_interpreter_settings

    @request_scope
    @provider
    def _provide_api_key(
        self, api_key: DIAL_API_KEY, py_interpreter_settings: _PyInterpreterSettings
    ) -> _PY_INTERPRETER_API_KEY:
        if py_interpreter_settings.local_run:
            if not py_interpreter_settings.api_key:
                raise ValueError("API key for local run with python interpreter is not set.")
            return py_interpreter_settings.api_key
        return api_key


class TestApp(FastAPI):

    @classmethod
    def get_app(cls, port: int = 8081):
        injector = Injector(
            [
                AppModule(),
                AgentModule(),
                RestApiToolingModule(),
                DialDeploymentToolingModule(),
                MCPToolingModule(),
                PyInterpreterTestModule(),
                AttachmentProcessingModule(),
                TimestampModule(),
                DialCoreServicesModule(),
                FileTransferModule(),
                SkillsModule(),
            ]
        )
        dial_settings = DialSettings(url=TestConfig.get_mock_dial_core_url(port))
        injector.binder.bind(DialSettings, to=dial_settings, scope=singleton)

        return injector.get(FastAPI)
