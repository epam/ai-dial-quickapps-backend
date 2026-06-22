import json
import logging
import os
from enum import Enum

from pydantic import SecretStr
from pydantic.type_adapter import TypeAdapter

from quickapp.config.application import ApplicationConfig, Features, OrchestratorConfig
from quickapp.config.context import Context
from quickapp.config.dial_deployment import DialDeploymentConfig, DialDeploymentParameters
from quickapp.config.dial_files import DialFilesConfig
from quickapp.config.orchestrator_attachment_strategy import LazyOnDemandAttachmentStrategy
from quickapp.config.prompt import PredefinedSystemPromptConfig
from quickapp.config.skill import DialPromptSkillConfig
from quickapp.config.toolsets.toolset import ToolSet
from tests.integration_tests.test_runner.paths import TOOLSETS_DIR
from tests.integration_tests.test_runner.test_tool_set_rest import TestToolSetRest

logger = logging.getLogger(__name__)

file_sets = {
    "integration": ["test_tool_set_chat_hub", "test_tool_set_py_interpreter", "test_mcp_tool"],
    "integration_simple": ["test_tool_set_chat_hub"],
    "e2e": ["test_tool_set_chat_hub", "test_tool_set_py_interpreter"],
    "no-additional-tools": [],
}


class SimilarityThreshold(Enum):
    DEFAULT = 0.9
    STRICT = 0.95
    LENIENT = 0.8


class TestDialCoreConfig:
    APP_NAME: str = os.getenv("DIAL_APP_NAME", "quick_app_2")  # used for telemetry
    APP_DEPLOYMENT_V2_NAME: str = os.getenv("APP_DEPLOYMENT_NAME", "quick_app_2")
    REMOTE_DIAL_URL: str = os.getenv("DIAL_URL", "http://localhost:8090")
    REMOTE_DIAL_API_KEY: str = os.getenv("DIAL_API_KEY", "dial_api_key")
    REMOTE_DIAL_API_KEY_SECRET = SecretStr(REMOTE_DIAL_API_KEY)
    LOG_LEVEL: str = os.getenv("DIAL_LOG_LEVEL", "INFO")
    MAX_MODEL_RETRIES: int = int(os.getenv("MAX_MODEL_RETRIES", 3))


class TestConfig:
    API_ENDPOINTS = {
        'CHAT_COMPLETIONS': '/openai/deployments/quick_apps2/chat/completions?api-version=2025-01-01-preview'
    }

    # MOCK_DIAL_CORE_PORT = int(os.getenv("MOCK_DIAL_CORE_PORT", "8081"))
    MOCK_DIAL_CORE_URL = "http://localhost:"

    DEFAULT_MODEL = os.getenv("MODEL", "gpt4_1")  # "gpt4o", "claude35", "claude37"

    PY_INTERPRETER_URL = os.getenv("PY_INTERPRETER_URL")
    PY_INTERPRETER_API_KEY = SecretStr(
        os.getenv("PY_INTERPRETER_API_KEY", TestDialCoreConfig.REMOTE_DIAL_API_KEY)
    )

    WARNING_MESSAGE = "No cached value found, this means that something was changed in the logic"
    FAILURE_MESSAGE = "Rerun locally the test with REFRESH=True to renew cached LLM responses"

    @classmethod
    def create_app_configuration(
        cls,
        toolsets: list[ToolSet],
        model: str,
        skill_urls: list[str] | None = None,
        contexts: list[Context] | None = None,
        attachment_strategy: LazyOnDemandAttachmentStrategy | None = None,
    ) -> ApplicationConfig:
        temperature = 0
        if "gemini" in model:
            template = "gemini_prompt"
        elif "claude" in model:
            template = "anthropic_prompt"
        else:
            if "gpt-5" in model:
                temperature = 1
            template = "gpt_prompt"

        skills = [DialPromptSkillConfig(url=url) for url in skill_urls] if skill_urls else None

        return ApplicationConfig(
            orchestrator=OrchestratorConfig(
                deployment=DialDeploymentConfig(
                    deployment_id=model,
                    parameters=DialDeploymentParameters(temperature=temperature),
                ),
                system_prompt=PredefinedSystemPromptConfig(template=template),
                attachment_strategy=attachment_strategy,
            ),
            contexts=contexts or [],
            tool_sets=toolsets,
            skills=skills,
            features=Features(dial_files=DialFilesConfig()),
        )

    @classmethod
    def load_tools_config(
        cls,
        port: int,
        config_file_set: str = "e2e",
        include_rest_toolset: bool = True,
    ) -> list[ToolSet]:
        files_list = file_sets.get(config_file_set) or []
        tool_set_list: list[ToolSet] = []
        for file in files_list:
            file_path = TOOLSETS_DIR / f"{file}.json"
            data = json.loads(file_path.read_text())
            tool_set: ToolSet = TypeAdapter(ToolSet).validate_python(data)
            tool_set_list.append(tool_set)
        if include_rest_toolset:
            tool_set_list.append(TestToolSetRest.get_rest_toolset(port=port))
        return tool_set_list

    @classmethod
    def get_mock_dial_core_url(cls, mock_dial_core_port):
        url = TestConfig.MOCK_DIAL_CORE_URL + str(mock_dial_core_port)
        logger.debug(f"Build dial_core mock url:{url}")
        return url
