import logging

from fastapi import FastAPI
from injector import Injector

from quickapp.agent.agent_module import AgentModule
from quickapp.application import AppModule
from quickapp.common.base_initializer import InitializerType, invoke_initializers
from quickapp.config.settings import load_logging_config
from quickapp.configuration_support import ConfigurationSupportApiModule
from quickapp.dial_core_services.dial_core_services_module import DialCoreServicesModule
from quickapp.dial_deployment_tooling import DialDeploymentToolingModule
from quickapp.internal_tooling.internal_tooling_module import InternalToolModule
from quickapp.mcp_tooling import MCPToolingModule
from quickapp.rest_api_tooling import RestApiToolingModule
from quickapp.starters.starters_module import StartersModule

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
        load_logging_config()
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
            ]
        )
        app = injector.get(FastAPI)

        @app.on_event("startup")
        async def startup_event():
            await invoke_initializers(injector, InitializerType.startup)

        logger.info("All modules successfully configured")
        return app
