from aidial_sdk.pydantic_v1 import SecretStr
from fastapi import FastAPI, HTTPException, Request, status
from injector import inject
from pydantic import TypeAdapter

from quickapp.config.config_template_resolver import ConfigResolver, TemplateType
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.toolsets.predefined import PredefinedToolSet
from quickapp.config.toolsets.toolset import ToolSet
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService

CONFIG_SUPPORT_URI = "/quickapps/v1/configuration-support"


@inject
class _Controller:

    def __init__(self, config_resolver: ConfigResolver, service: ToolConfigCoreService):
        self.__config_resolver = config_resolver
        self.__service = service

    def register_routes(self, app: FastAPI):
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
            return self._get_template_content(TemplateType.system_prompt, deployment_name)

        @app.get(CONFIG_SUPPORT_URI + "/tool-sets/{toolset_name}")
        async def get_toolset_content(toolset_name: str):
            return self._get_template_content(TemplateType.tool_set, toolset_name)

        @app.get(CONFIG_SUPPORT_URI + "/tools/{tool_name}")
        async def get_tool_content(tool_name: str):
            return self._get_template_content(TemplateType.tool, tool_name)

        @app.get(CONFIG_SUPPORT_URI + "/template/{deployment}", response_model=DialDeploymentTool)
        async def get_tool_template(deployment: str, request: Request):
            api_key = SecretStr(request.headers.get("api-key", ""))
            return await self.__service.get_basic_tool_config(deployment, api_key)

    def _get_template_content(self, template_type: TemplateType, template_name: str):
        templates = self.__config_resolver.template_map.get(template_type.value, [])  # type: ignore[union-attr]
        if template_name not in templates:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{template_type.value.capitalize()} '{template_name}' not found.",
            )
        try:
            template_content = self.__config_resolver.read_template_content(
                template_type, template_name
            )  # type: ignore[union-attr]
            if template_type in [TemplateType.system_prompt, TemplateType.tool]:
                return template_content
            elif template_type == TemplateType.tool_set:
                actual_tool_set: PredefinedToolSet = TypeAdapter(ToolSet).validate_python(
                    template_content
                )
                return self.__config_resolver.resolve_predefined_toolset(actual_tool_set)
        except FileNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to load {template_type.value} '{template_name}': {e}",
            )
