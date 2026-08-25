from fastapi import FastAPI
from fastapi_injector import request_scope
from injector import Injector, provider, singleton

from quickapp.attachment_processing.attachment_processing_module import AttachmentProcessingModule
from quickapp.common import DIAL_API_KEY
from quickapp.common.dial_settings import DialSettings
from quickapp.configuration_support import ConfigurationSupportApiModule
from quickapp.core import core_module
from quickapp.dial_app_tooling import DialAppToolingModule
from quickapp.dial_core_services.dial_core_services_module import DialCoreServicesModule
from quickapp.dial_deployment_tooling import DialDeploymentToolingModule
from quickapp.dial_files_tooling.dial_files_tooling_module import DialFilesToolingModule
from quickapp.dial_prompt_skills.dial_prompt_skills_module import DialPromptSkillsModule
from quickapp.file_transfer import FileTransferModule
from quickapp.internal_tooling.internal_tooling_module import InternalToolModule
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_client import (
    _PyInterpreterClient,
)
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_settings import (
    _PY_INTERPRETER_API_KEY,
    _PyInterpreterSettings,
)
from quickapp.mcp_tooling import MCPToolingModule
from quickapp.orchestrator_attachment_strategies.lazy_on_demand.lazy_on_demand_strategy_module import (
    LazyOnDemandStrategyModule,
)
from quickapp.predefined_tooling import PredefinedToolingModule
from quickapp.rest_api_tooling import RestApiToolingModule
from quickapp.shared import shared_module
from quickapp.skills.skills_module import SkillsModule
from quickapp.starters.starters_module import StartersModule
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
                *core_module,
                *shared_module,
                PredefinedToolingModule(),
                RestApiToolingModule(),
                DialDeploymentToolingModule(),
                DialAppToolingModule(),
                MCPToolingModule(),
                PyInterpreterTestModule(),
                StartersModule(),
                ConfigurationSupportApiModule(),
                DialCoreServicesModule(),
                FileTransferModule(),
                AttachmentProcessingModule(),
                SkillsModule(),
                DialPromptSkillsModule(),
                DialFilesToolingModule(),
                LazyOnDemandStrategyModule(),
            ]
        )
        dial_settings = DialSettings(url=TestConfig.get_mock_dial_core_url(port))
        injector.binder.bind(DialSettings, to=dial_settings, scope=singleton)

        return injector.get(FastAPI)
