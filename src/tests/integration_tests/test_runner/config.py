import json
import logging
import os
from enum import Enum
from pathlib import Path
from typing import List

from pydantic import SecretStr

from quickapp.config.application import ApplicationConfig, OrchestratorConfig
from quickapp.config.dial_deployment import DialDeploymentConfig, DialDeploymentParameters
from quickapp.config.prompt import PredefinedSystemPromptConfig
from quickapp.config.toolsets.toolset import ToolSet
from pydantic.type_adapter import TypeAdapter

from tests.integration_tests.test_runner.test_tool_set_rest import TestToolSetRest

logger = logging.getLogger(__name__)

file_sets = {
    "integration": ["test_tool_set_chat_hub", "test_tool_set_py_interpreter", "test_mcp_tool"],
    "e2e": ["test_tool_set_chat_hub", "test_tool_set_py_interpreter"]
}

class SimilarityThreshold(Enum):
    DEFAULT = 0.9
    STRICT = 0.95
    LENIENT = 0.8


class TestDialCoreConfig:
    APP_NAME: str = os.getenv("DIAL_APP_NAME", "quick_app_2")  # used for telemetry
    APP_DEPLOYMENT_V2_NAME: str = os.getenv("APP_DEPLOYMENT_NAME", "quick_app_2")
    REMOTE_DIAL_URL: str = os.getenv("REMOTE_DIAL_URL", "http://localhost:8090")
    LOG_LEVEL: str = os.getenv("DIAL_LOG_LEVEL", "INFO")
    MAX_MODEL_RETRIES: int = int(os.getenv("MAX_MODEL_RETRIES", 3))


class TestConfig:
    API_ENDPOINTS = {
        'CHAT_COMPLETIONS': '/openai/deployments/quick_apps2/chat/completions?api-version=2025-01-01-preview'
    }

    # MOCK_DIAL_CORE_PORT = int(os.getenv("MOCK_DIAL_CORE_PORT", "8081"))
    MOCK_DIAL_CORE_URL = "http://localhost:"

    DEFAULT_MODEL = os.getenv("MODEL", "gpt4_1")  # "gpt4o", "claude35", "claude37"
    REMOTE_DIAL_API_KEY = SecretStr(os.getenv("REMOTE_DIAL_API_KEY", "dial_api_key"))

    PY_INTERPRETER_URL = "https://dev-dial-core.staging.deltixhub.io"
    PY_INTERPRETER_API_KEY = SecretStr(os.getenv("PY_INTERPRETER_API_KEY", REMOTE_DIAL_API_KEY))

    WARNING_MESSAGE = "No cached value found, this means that something was changed in the logic"
    FAILURE_MESSAGE = "Rerun locally the test with REFRESH=True to renew cached LLM responses"

    @classmethod
    def create_app_configuration(cls, toolsets: list[ToolSet], model) -> ApplicationConfig:
        temperature = 0
        if "gemini" in model:
            template = "gemini_prompt"
        elif "claude" in model:
            template = "anthropic_prompt"
        else:
            if "gpt-5" in model:
                temperature = 1
            template = "gpt_prompt"

        return ApplicationConfig(
            orchestrator=OrchestratorConfig(
                deployment=DialDeploymentConfig(name=model, parameters=DialDeploymentParameters(temperature=temperature)),
                system_prompt=PredefinedSystemPromptConfig(template=template),
            ),
            contexts=[],
            tool_sets=toolsets
        )

    @classmethod
    def load_tools_config(cls, port: int, config_file_set: str = "e2e") -> list[ToolSet]:
        files_list = file_sets.get(config_file_set)
        tool_set_list: List[ToolSet] = []
        for file in files_list:
            file_path = Path(__file__).parent / f"{file}.json"
            data = json.loads(file_path.read_text())
            tool_set = TypeAdapter(ToolSet).validate_python(data)
            tool_set_list.append(tool_set)
        tool_set_list.append(TestToolSetRest.get_rest_toolset(port=port))
        return tool_set_list

    @classmethod
    def get_mock_dial_core_url(cls, mock_dial_core_port):
        url = TestConfig.MOCK_DIAL_CORE_URL + str(mock_dial_core_port)
        logger.debug(f"Build dial_core mock url:{url}")
        return url
