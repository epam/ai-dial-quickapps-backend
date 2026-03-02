from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from injector import inject
from pydantic import SecretStr, TypeAdapter

from quickapp.config.application import ApplicationConfig
from quickapp.config.config_template_resolver import ConfigResolver
from quickapp.config.predefined_content_provider import ContentType
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.toolsets.toolset import ToolSet
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService

CONFIG_SUPPORT_URI = "/v1/configuration-support"


@inject
class _Controller:

    def __init__(self, config_resolver: ConfigResolver, service: ToolConfigCoreService):
        self.__config_resolver = config_resolver
        self.__service = service

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

    def _get_template_content(self, template_type: ContentType, template_name: str) -> Any:
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
