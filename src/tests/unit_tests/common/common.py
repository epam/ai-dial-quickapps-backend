import json
from collections.abc import Callable, Iterable
from typing import TypeAlias
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
from fastapi import FastAPI
from fastapi_injector import InjectorMiddleware, RequestScopeOptions, attach_injector
from injector import Binder, Injector, Module, ProviderOf

from quickapp.common import ToolCallResult
from quickapp.config.application import ApplicationConfig, OrchestratorConfig
from quickapp.config.dial_deployment import DialDeploymentConfig, DialDeploymentParameters
from quickapp.config.prompt import CustomSystemPromptConfig
from quickapp.config.tools.base import AttachmentConfig
from quickapp.config.toolsets.toolset import ToolSet
from quickapp.dial_core_services.deployment_names_service import DeploymentNamesCoreService
from quickapp.shared.user_access import ToolAccessFilter
from quickapp.skills import ResolvedSkill, SkillFileReader
from quickapp.skills.skill_metadata import SkillMetadata

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
                deployment_id="gpt-4o-mini-2024-07-18",
                parameters=DialDeploymentParameters(),
            ),
            system_prompt=CustomSystemPromptConfig(
                type="custom", content="test", variables={"test": "test"}
            ),
        ),
        contexts=[],
        tool_sets=toolsets,
    )


def build_tool_expected_result(tool_result: ToolCallResult):
    result_dict = tool_result.model_dump()
    result_dict["propagate_to_choice"] = AttachmentConfig()
    return result_dict


def make_deployment_names_service(names: list[str] | Exception) -> MagicMock:
    """`DeploymentNamesCoreService` double whose ``list_names`` returns ``names`` (or raises it if an Exception)."""
    service = MagicMock(spec=DeploymentNamesCoreService)
    if isinstance(names, Exception):
        service.list_names = AsyncMock(side_effect=names)
    else:
        service.list_names = AsyncMock(return_value=names)
    return service


def make_access_filter(
    app_config: ApplicationConfig | None = None,
    deployment_names_service: MagicMock | None = None,
) -> ToolAccessFilter:
    """Real `ToolAccessFilter`; inert unless ``app_config`` enables ``features.tool_access_filter``."""
    return ToolAccessFilter(
        app_config=app_config or create_app_configuration([]),
        deployment_names_service=deployment_names_service or make_deployment_names_service([]),
    )


def noop_timeout_resolver(value: float = 300.0) -> MagicMock:
    """MagicMock for `ToolTimeoutResolver` where `.resolve()` returns ``value``."""
    return MagicMock(resolve=MagicMock(return_value=value))


def make_provider(value: object) -> MagicMock:
    """MagicMock for `ProviderOf[T]` whose `.get()` returns ``value``."""
    provider = MagicMock(spec=ProviderOf)
    provider.get.return_value = value
    return provider


def noop_timeout_resolver_provider(value: float = 300.0) -> MagicMock:
    """MagicMock for `ProviderOf[ToolTimeoutResolver]` whose `.get()` returns ``noop_timeout_resolver(value)``."""
    return make_provider(noop_timeout_resolver(value=value))


def make_resolved_skill(
    url: str,
    name: str,
    description: str = "A skill",
    content: str = "body",
    files: tuple[str, ...] = (),
    reader: SkillFileReader | None = None,
) -> ResolvedSkill:
    """Builder for ``ResolvedSkill`` fixtures shared across skills tests."""
    return ResolvedSkill(
        url=url,
        metadata=SkillMetadata(name=name, description=description),
        content=content,
        files=files,
        reader=reader,
    )


def make_openai_status_error(
    cls: type[openai.APIStatusError], status_code: int, body: object = None
) -> openai.APIStatusError:
    """An openai status error as the deployment client raises it; the message is a raw detail
    that must never reach the user."""
    request = httpx.Request("POST", "http://dial-core/openai/deployments/model/chat/completions")
    return cls(
        "raw upstream detail", response=httpx.Response(status_code, request=request), body=body
    )
