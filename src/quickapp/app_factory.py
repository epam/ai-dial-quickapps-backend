import logging

from fastapi import FastAPI
from injector import Injector

from quickapp.agent.agent_module import AgentModule
from quickapp.application import AppModule
from quickapp.attachment_processing.attachment_processing_module import AttachmentProcessingModule
from quickapp.common.base_initializer import InitializerType, invoke_initializers
from quickapp.config.logging_config import LoggingConfig
from quickapp.config.logging_settings import LoggingSettings
from quickapp.configuration_support import ConfigurationSupportApiModule
from quickapp.dial_core_services.dial_core_services_module import DialCoreServicesModule
from quickapp.dial_deployment_tooling import DialDeploymentToolingModule
from quickapp.internal_tooling.internal_tooling_module import InternalToolModule
from quickapp.mcp_tooling import MCPToolingModule
from quickapp.rest_api_tooling import RestApiToolingModule
from quickapp.skills.skills_module import SkillsModule
from quickapp.starters.starters_module import StartersModule
from quickapp.timestamp_tooling import TimestampModule

logger = logging.getLogger(__name__)


class AppFactory:
    """
    Factory class to create and configure the FastAPI application with dependency injection.
    """

    @staticmethod
    def create() -> FastAPI:
        """
        Creates and configures the FastAPI application with the necessary modules.

        Returns:
            FastAPI: The configured FastAPI application instance.
        """
        LoggingConfig(settings=LoggingSettings())
        injector = Injector(
            [
                AppModule(),
                AgentModule(),
                RestApiToolingModule(),
                DialDeploymentToolingModule(),
                MCPToolingModule(),
                InternalToolModule(),
                TimestampModule(),
                StartersModule(),
                ConfigurationSupportApiModule(),
                DialCoreServicesModule(),
                AttachmentProcessingModule(),
                SkillsModule(),
            ]
        )
        app = injector.get(FastAPI)

        @app.on_event("startup")
        async def startup_event():
            await invoke_initializers(injector, InitializerType.startup)

        logger.info("All modules successfully configured")
        return app
