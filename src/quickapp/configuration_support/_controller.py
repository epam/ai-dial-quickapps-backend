import logging
from typing import Any

from aidial_client import AsyncDial, DialException
from fastapi import FastAPI, HTTPException, Request, status
from injector import inject

from quickapp.common.dial_settings import DialSettings
from quickapp.config.application import ApplicationConfig
from quickapp.config.skill import DialPromptSkillConfig, SkillConfig
from quickapp.dial_prompt_skills._dial_prompt_skill_resolver import (
    fetch_and_validate_dial_prompt_skill,
)
from quickapp.predefined_tooling import PredefinedConfigResolver
from quickapp.skills._exceptions import SkillValidationError
from quickapp.skills._skill_metadata import SkillMetadata
from quickapp.skills.agent_skills_provider import AgentSkillsProvider

logger = logging.getLogger(__name__)

CONFIG_SUPPORT_URI = "/v1/configuration-support"


@inject
class _Controller:

    def __init__(
        self,
        config_resolver: PredefinedConfigResolver,
        skills_provider: AgentSkillsProvider,
        dial_settings: DialSettings,
    ):
        self.__config_resolver = config_resolver
        self.__skills_provider = skills_provider
        self.__dial_settings = dial_settings

    def register_routes(self, app: FastAPI) -> None:
        @app.get(CONFIG_SUPPORT_URI + "/application-schema")
        async def get_app_schema():
            return ApplicationConfig.model_json_schema(include_dial_fields=False)

        @app.get(CONFIG_SUPPORT_URI + "/default-configuration")
        async def get_default_configuration() -> dict[str, Any]:
            return self.__config_resolver.get_default_configuration()

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
            parsed, _ = await fetch_and_validate_dial_prompt_skill(dial_client, config.url)
            for warning in parsed.warnings:
                logger.warning("Skill validation '%s': %s", config.url, warning)
            return parsed.metadata
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
