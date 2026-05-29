import logging
from typing import Any

from aidial_client import AsyncDial, DialException, ToolsetInfo
from aidial_client.types.application import Application
from aidial_client.types.deployment import Deployment
from aidial_sdk.chat_completion.request import StaticTool
from injector import ProviderOf, inject
from pydantic import SecretStr

from quickapp.common.dial_settings import DialSettings
from quickapp.common.tool_timeout_utils import build_async_dial_timeout
from quickapp.common.utils import sanitize_toolname
from quickapp.config.dial_deployment import DialDeploymentConfig
from quickapp.config.tools.base import (
    ConfigurableSchemaArray,
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.tools.display.paramenter import (
    FormattedParameterConfig,
    ParameterDisplayConfig,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.tool_fallback import ContinueStrategyModel, ToolFallbackConfig
from quickapp.config_resolvers.tool_timeout_resolver import ToolTimeoutResolver
from quickapp.dial_core_services.exceptions import (
    ToolsetForbiddenException,
    ToolsetNotFoundException,
)

logger = logging.getLogger(__name__)

STATIC_FUNCTION_TYPE = "static_function"
TOOLS_KEY = "tools"
TYPE_KEY = "type"


@inject
class ToolConfigCoreService:

    def __init__(
        self,
        dial_settings: DialSettings,
        dial_client_provider: ProviderOf[AsyncDial],
        timeout_resolver_provider: ProviderOf[ToolTimeoutResolver],
    ):
        self.__dial_settings: DialSettings = dial_settings
        self.__dial_client_provider: ProviderOf[AsyncDial] = dial_client_provider
        self.__timeout_resolver_provider: ProviderOf[ToolTimeoutResolver] = (
            timeout_resolver_provider
        )

    def _resolve_dial_client(self, api_key: SecretStr | None) -> AsyncDial:
        """Return a client built from the explicit key (controller path) or from the DI provider (completion path)."""
        if api_key is not None:
            return AsyncDial(
                api_key=api_key.get_secret_value(),
                base_url=self.__dial_settings.url,
                api_version=self.__dial_settings.api_version,
                timeout=build_async_dial_timeout(self.__timeout_resolver_provider.get().resolve()),
            )
        return self.__dial_client_provider.get()

    @staticmethod
    def parse_static_tools_from_info(
        deployment: Deployment | Application,
    ) -> list[StaticTool]:
        """Extract and parse defaults.tools from deployment or application info.

        Supports type == "static_function"; other types are skipped with a debug log.
        Returns empty list if defaults or defaults.tools are missing.
        """
        defaults = deployment.defaults
        if not isinstance(defaults, dict):
            return []
        raw_tools = defaults.get(TOOLS_KEY)
        if not isinstance(raw_tools, list):
            return []
        result: list[StaticTool] = []
        for entry in raw_tools:
            if not isinstance(entry, dict):
                continue
            tool_type = entry.get(TYPE_KEY)
            if tool_type == STATIC_FUNCTION_TYPE:
                try:
                    static_tool = StaticTool.model_validate(entry)
                    result.append(static_tool)
                except Exception:
                    logger.debug(
                        "Skipping invalid static_function entry in defaults.tools: %s",
                        entry,
                        exc_info=True,
                    )
            else:
                logger.debug(
                    "Skipping unsupported default tool type: %s (deployment defaults.tools)",
                    tool_type,
                )
        return result

    @staticmethod
    async def _fetch_deployment_or_application(
        dial_client: AsyncDial, deployment: str
    ) -> Deployment | Application:
        deployment_model: Deployment | None = None
        application_model: Application | None = None
        try:
            logger.debug(f"Getting deployment metadata for {deployment}")
            deployment_model = await dial_client.deployments.get(deployment)
        except DialException as e:
            if e.status_code == 404:
                logger.debug(f"No deployment found, trying application for {deployment}")
                application_model = await dial_client.application.get(deployment)
            else:
                raise

        model = deployment_model or application_model
        if model is None:
            raise RuntimeError(f"Neither deployment nor application found for '{deployment}'")
        return model

    async def get_deployment_metadata(
        self, deployment: str, api_key: SecretStr | None = None
    ) -> Deployment | Application:
        dial_client = self._resolve_dial_client(api_key)
        return await self._fetch_deployment_or_application(dial_client, deployment)

    async def get_basic_tool_config(
        self, deployment: str, api_key: SecretStr | None = None
    ) -> DialDeploymentTool:
        dial_client = self._resolve_dial_client(api_key)
        model = await self._fetch_deployment_or_application(dial_client, deployment)

        config_schema: dict[str, Any] | None = None
        if model.features and model.features.configuration:
            logger.debug(f"Getting configuration schema for {deployment}")
            config_schema = await dial_client.deployments.get_configuration_schema(deployment)

        return ToolConfigCoreService._convert_to_openai_tool_format(model, config_schema)

    @staticmethod
    def _convert_to_openai_tool_format(
        deployment: Deployment | Application, config: dict[str, Any] | None = None
    ) -> DialDeploymentTool:
        """
        Converts DIAL API responses into a structured OpenAI-like tool definition.

        Args:
            deployment: The parsed Pydantic model of the deployment info.
            config: The JSON response from get_configuration_schema (if available).

        Returns:
            A DialDeploymentTool representing the final tool configuration.
        """

        # Deployment display_name could contain anything including Cyrillic symbols
        # deployment.id is already quoted url string like applications/{hash}/deployment%20name.
        # To make it more readable:
        # - replace %20(space) with _
        # - remove bucket prefix
        deployment_name = sanitize_toolname(
            f"{deployment.id.split('/')[-1].replace('%20', '_')}_tool"
        )

        output_tool = DialDeploymentTool(
            display=ToolDisplayConfig(stage=ToolStageConfig(name=f"Call {deployment_name}: ")),
            deployment=DialDeploymentConfig(deployment_id=deployment.id),
            fallback_configuration=ToolFallbackConfig(strategies=[ContinueStrategyModel()]),
            open_ai_tool=OpenAiToolConfig(
                function=OpenAiToolFunction(
                    name=deployment_name,
                    description=deployment.description or "",
                    parameters=OpenAiToolFunctionParameters(
                        type=JsonTypeEnum.object, properties={}, required=[]
                    ),
                )
            ),
        )

        properties: dict[str, ConfigurableSchemaSimpleType | ConfigurableSchemaArray] = {}
        required_params: list[str] = []
        properties["query"] = ConfigurableSchemaSimpleType(
            type=JsonTypeEnum.string,
            description="The query for the tool.",
            display=ParameterDisplayConfig(stage=FormattedParameterConfig(name="**Prompt:** ")),
        )
        required_params.append("query")

        # Handle attachments if the tool supports them
        if deployment.input_attachment_types:
            properties["attachment_urls"] = ConfigurableSchemaArray(
                type=JsonTypeEnum.array,
                items=ConfigurableSchemaSimpleType(
                    type=JsonTypeEnum.string,
                    description="Attachment url related to tool call. Use full url.",
                    display=ParameterDisplayConfig(
                        stage=FormattedParameterConfig(name="**Prompt:** ")
                    ),
                ),
                description="The list of attachment urls related to tool call. Use full url for each item in the list. If no attachments are related use empty list argument value.",
            )

            required_params.append("attachment_urls")

        configuration_param_names: set[str] = set()
        if config and config.get("properties"):
            config_required = set(config.get("required", []))
            for param_name, param_details in config["properties"].items():
                logger.debug(f"Processing parameter: {param_name} with details: {param_details}")
                configuration_param_names.add(param_name)
                # Extract enum values from the 'anyOf' structure
                enum_values = []
                if "anyOf" in param_details:
                    for item in param_details["anyOf"]:
                        if "enum" in item:
                            enum_values.extend(item["enum"])

                properties[param_name] = ConfigurableSchemaSimpleType(
                    type=JsonTypeEnum.string,
                    description=param_details.get("description", ""),
                    enum=enum_values or None,
                    default=param_details.get("default"),
                    display=ParameterDisplayConfig(stage=FormattedParameterConfig(ignore=True)),
                )
                if param_name in config_required:
                    required_params.append(param_name)

        output_tool.open_ai_tool.function.parameters.properties = properties
        output_tool.open_ai_tool.function.parameters.required = sorted(set(required_params))
        output_tool.deployment._configuration_param_names = configuration_param_names

        return output_tool

    async def get_basic_toolset_config(self, toolset_dial_id: str) -> ToolsetInfo | None:
        dial_client = self.__dial_client_provider.get()
        try:
            logger.debug(f"Getting toolset tool config for {toolset_dial_id}")
            return await dial_client.toolset.get(toolset_dial_id)
        except DialException as e:
            logger.exception("Something went wrong during getting toolset %s", toolset_dial_id)
            if e.status_code == 404:
                raise ToolsetNotFoundException(
                    toolset_id=toolset_dial_id,
                    details=f"{e.status_code} {e.message}",
                )
            elif e.status_code == 403:
                raise ToolsetForbiddenException(
                    toolset_id=toolset_dial_id,
                    details=f"{e.status_code} {e.message}",
                )
            raise
