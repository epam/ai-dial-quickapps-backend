from fastapi import FastAPI
from injector import Injector

from quickapp.agent.agent_module import AgentModule
from quickapp.application import AppModule
from quickapp.attachment_processing.attachment_processing_module import AttachmentProcessingModule
from quickapp.config.logging_config import LoggingConfig
from quickapp.config.logging_settings import LoggingSettings
from quickapp.configuration_support import ConfigurationSupportApiModule
from quickapp.dial_core_services.dial_core_services_module import DialCoreServicesModule
from quickapp.dial_deployment_tooling import DialDeploymentToolingModule
from quickapp.file_transfer import FileTransferModule
from quickapp.internal_tooling.internal_tooling_module import InternalToolModule
from quickapp.mcp_tooling import MCPToolingModule
from quickapp.rest_api_tooling import RestApiToolingModule
from quickapp.skills.skills_module import SkillsModule
from quickapp.starters.starters_module import StartersModule


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
                StartersModule(),
                ConfigurationSupportApiModule(),
                DialCoreServicesModule(),
                FileTransferModule(),
                AttachmentProcessingModule(),
                SkillsModule(),
            ]
        )
        app = injector.get(FastAPI)
        return app
