from typing import Any

from aidial_client import AsyncDial, DialException
from fastapi import FastAPI, HTTPException, Request, status
from injector import inject
from pydantic import SecretStr, TypeAdapter

from quickapp.common.dial_settings import DialSettings
from quickapp.config.application import ApplicationConfig
from quickapp.config.predefined_content_provider import ContentType
from quickapp.config.skill import DialPromptSkillConfig, SkillConfig
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.toolsets.toolset import ToolSet
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService
from quickapp.dial_prompt_skills._dial_prompt_skill_resolver import (
    fetch_and_validate_dial_prompt_skill,
)
from quickapp.predefined_tooling import PredefinedConfigResolver
from quickapp.skills._exceptions import SkillValidationError
from quickapp.skills._skill_metadata import SkillMetadata
from quickapp.skills.agent_skills_provider import AgentSkillsProvider

CONFIG_SUPPORT_URI = "/v1/configuration-support"


@inject
class _Controller:

    def __init__(
        self,
        config_resolver: PredefinedConfigResolver,
        service: ToolConfigCoreService,
        skills_provider: AgentSkillsProvider,
        dial_settings: DialSettings,
    ):
        self.__config_resolver = config_resolver
        self.__service = service
        self.__skills_provider = skills_provider
        self.__dial_settings = dial_settings

    def register_routes(self, app: FastAPI) -> None:
        @app.get(CONFIG_SUPPORT_URI + "/application-schema")
        async def get_app_schema():
            return ApplicationConfig.model_json_schema(include_dial_fields=False)

        @app.get(CONFIG_SUPPORT_URI + "/system-prompts")
        async def get_system_prompts():
            return self.__config_resolver.get_prompts()

        @app.get(CONFIG_SUPPORT_URI + "/tool-sets")
        async def get_tool_sets():
            return self.__config_resolver.get_tool_sets()

        @app.get(CONFIG_SUPPORT_URI + "/tools")
        async def get_tools():
            return self.__config_resolver.get_tools()

        @app.get(CONFIG_SUPPORT_URI + "/system-prompts/{deployment_name}")
        async def get_system_prompt_content(deployment_name: str):
            return self._get_template_content(ContentType.PROMPT, deployment_name)

        @app.get(CONFIG_SUPPORT_URI + "/tool-sets/{toolset_name}")
        async def get_toolset_content(toolset_name: str):
            return self._get_template_content(ContentType.TOOLSET, toolset_name)

        @app.get(CONFIG_SUPPORT_URI + "/tools/{tool_name}")
        async def get_tool_content(tool_name: str):
            return self._get_template_content(ContentType.TOOL, tool_name)

        @app.get(CONFIG_SUPPORT_URI + "/template/{deployment}", response_model=DialDeploymentTool)
        async def get_tool_template(deployment: str, request: Request):
            api_key = SecretStr(request.headers.get("api-key", ""))
            return await self.__service.get_basic_tool_config(deployment, api_key)

        @app.get(CONFIG_SUPPORT_URI + "/skills")
        async def get_skills() -> list[SkillMetadata]:
            return self.__skills_provider.get_all_skills()

        @app.post(CONFIG_SUPPORT_URI + "/skills/validate", response_model=SkillMetadata)
        async def validate_skill(config: SkillConfig, request: Request) -> SkillMetadata:
            if isinstance(config, DialPromptSkillConfig):
                return await self._validate_dial_prompt_skill(config, request)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported skill type: {config.type}",
            )

    async def _validate_dial_prompt_skill(
        self,
        config: DialPromptSkillConfig,
        request: Request,
    ) -> SkillMetadata:
        api_key = request.headers.get("api-key", "")
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing api-key header",
            )

        dial_client = AsyncDial(
            base_url=self.__dial_settings.url,
            api_key=api_key,
            api_version=self.__dial_settings.api_version,
        )

        try:
            metadata, _ = await fetch_and_validate_dial_prompt_skill(dial_client, config.url)
            return metadata
        except DialException as e:
            if e.status_code == 401:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid api-key",
                )
            if e.status_code in (403, 404):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Prompt not found or inaccessible: {config.url}",
                )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to fetch prompt: {e.message}",
            )
        except SkillValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(e),
            )

    def _get_template_content(
        self, template_type: ContentType, template_name: str
    ) -> str | dict[str, Any] | ToolSet:
        templates = self.__config_resolver.template_map.get(template_type.value, [])
        if template_name not in templates:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{template_type.value.capitalize()} '{template_name}' not found.",
            )
        try:
            content = self.__config_resolver.read_template_content(template_type, template_name)
            if template_type == ContentType.TOOLSET:
                tool_set: ToolSet = TypeAdapter(ToolSet).validate_python(content)
                return self.__config_resolver.resolve_toolset(tool_set)
            return content
        except FileNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to load {template_type.value} '{template_name}': {e}",
            )
