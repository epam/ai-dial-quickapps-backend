import json
from collections.abc import Callable, Iterable
from typing import TypeAlias
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi_injector import InjectorMiddleware, RequestScopeOptions, attach_injector
from injector import Binder, Injector, Module, ProviderOf

from quickapp.common import CompletionResult
from quickapp.config.application import ApplicationConfig, OrchestratorConfig
from quickapp.config.dial_deployment import DialDeploymentConfig, DialDeploymentParameters
from quickapp.config.prompt import CustomSystemPromptConfig
from quickapp.config.tools.base import AttachmentConfig
from quickapp.config.toolsets.toolset import ToolSet

MODULE_TYPE: TypeAlias = Callable[[Binder], None] | Module | type[Module]


def create_test_app(module_or_modules: MODULE_TYPE | Iterable[MODULE_TYPE]) -> FastAPI:
    app = FastAPI()
    binded_modules = (
        [module_or_modules] if not isinstance(module_or_modules, Iterable) else module_or_modules
    )
    injector = Injector(modules=binded_modules)
    # noinspection PyTypeChecker
    app.add_middleware(InjectorMiddleware, injector=injector)
    attach_injector(app, injector, RequestScopeOptions())
    return app


def create_request_headers(api_key: str, starters: list[str] | None) -> dict[str, str]:
    return {
        "Api-Key": api_key,
        "Content-Type": "application/json",
        "X-DIAL-APPLICATION-PROPERTIES": json.dumps(
            {
                "temperature": 0.7,
                "instructions": "test instructions",
                "model": "test_model",
                "web_api_toolset": [],
                "starters": starters,
            }
        ),
        "X-DIAL-APPLICATION-ID": "your_deployment_id",
    }


def create_request_body(message_content: str) -> dict[str, str]:
    return {
        "model": "test_model",
        "messages": [{"role": "user", "content": message_content}],
        "functions": [],
        "function_call": "auto",
        "tools": [],
        "tool_choice": "auto",
        "stream": False,
        "temperature": 0.7,
        "top_p": 0.9,
        "n": 1,
        "stop": None,
        "max_tokens": 100,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "logit_bias": {},
        "user": "test_user",
        "seed": None,
        "logprobs": None,
        "top_logprobs": None,
        "response_format": {"type": "text"},
        "custom_fields": {},
    }


def create_app_configuration(toolsets: list[ToolSet]) -> ApplicationConfig:
    return ApplicationConfig(
        orchestrator=OrchestratorConfig(
            deployment=DialDeploymentConfig(
                name="gpt-4o-mini-2024-07-18", parameters=DialDeploymentParameters()
            ),
            system_prompt=CustomSystemPromptConfig(
                type="custom", content="test", variables={"test": "test"}
            ),
        ),
        contexts=[],
        tool_sets=toolsets,
    )


def build_tool_expected_result(tool_result: CompletionResult):
    result_dict = tool_result.model_dump()
    result_dict["propagate_to_choice"] = AttachmentConfig()
    return result_dict


def noop_timeout_resolver(value: float = 300.0) -> MagicMock:
    """MagicMock for `ToolTimeoutResolver` where `.resolve()` returns ``value``."""
    return MagicMock(resolve=MagicMock(return_value=value))


def noop_timeout_resolver_provider(value: float = 300.0) -> MagicMock:
    """MagicMock for `ProviderOf[ToolTimeoutResolver]` whose `.get()` returns ``noop_timeout_resolver(value)``."""
    provider = MagicMock(spec=ProviderOf)
    provider.get.return_value = noop_timeout_resolver(value=value)
    return provider
