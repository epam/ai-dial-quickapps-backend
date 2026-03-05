import logging
from typing import Any

from aidial_client.types.application import Application
from aidial_client.types.deployment import Deployment
from httpx import HTTPStatusError
from injector import ProviderOf, inject
from pydantic import SecretStr

from quickapp.common import DIAL_API_KEY
from quickapp.common.dial_core_client import DialCoreClient, ToolsetInfo
from quickapp.common.dial_settings import DialSettings
from quickapp.config.dial_deployment import DialDeploymentConfig
from quickapp.config.tools.base import (
    AttachmentConfig,
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
from quickapp.dial_core_services.exceptions import (
    ToolsetForbiddenException,
    ToolsetNotFoundException,
)

logger = logging.getLogger(__name__)


@inject
class ToolConfigCoreService:

    def __init__(self, dial_settings: DialSettings, api_key_provider: ProviderOf[DIAL_API_KEY]):
        self.__dial_settings: DialSettings = dial_settings
        self.__api_key_provider: ProviderOf[DIAL_API_KEY] = api_key_provider

    async def get_basic_tool_config(
        self, deployment: str, api_key: SecretStr | None = None
    ) -> DialDeploymentTool:
        api_key = api_key or self.__api_key_provider.get()
        async with DialCoreClient(api_key=api_key, base_url=self.__dial_settings.url) as dial_core:
            deployment_model: Deployment | None = None
            application_model: Application | None = None
            try:
                logger.debug(f"Getting deployment tool config for {deployment}")
                info_dict = await dial_core.get_deployment_info(deployment)
                deployment_model = Deployment.model_validate(info_dict)
            except HTTPStatusError as e:
                if e.response.status_code == 404:
                    logger.debug(f"No deployment found, trying application for {deployment}")
                    info_dict = await dial_core.get_application_info(deployment)
                    application_model = Application.model_validate(info_dict)
            config_schema = None
            if (
                deployment_model
                and deployment_model.features
                and deployment_model.features.configuration
            ):
                logger.debug(f"Getting deployment config for {deployment}")
                config_schema = await dial_core.get_deployment_config(deployment)
            elif (
                application_model
                and application_model.features
                and application_model.features.configuration
            ):
                logger.debug(f"Getting application config for {deployment}")
                config_schema = await dial_core.get_deployment_config(deployment)

            model = deployment_model or application_model
            if model is None:
                raise RuntimeError(f"Neither deployment nor application found for '{deployment}'")
            return ToolConfigCoreService._convert_to_openai_tool_format(model, config_schema)

    @staticmethod
    def _convert_to_openai_tool_format(
        deployment: Deployment | Application, config: dict[str, Any] | None = None
    ) -> DialDeploymentTool:
        """
        Converts DIAL API responses into a structured OpenAI-like tool definition.

        Args:
            deployment: The parsed Pydantic model of the deployment info.
            config: The JSON response from get_deployment_config (if available).

        Returns:
            A DialDeploymentTool representing the final tool configuration.
        """
        output_tool = DialDeploymentTool(
            display=ToolDisplayConfig(stage=ToolStageConfig(name=f"Call {deployment.id}: ")),
            deployment=DialDeploymentConfig(name=deployment.id),
            attachment=AttachmentConfig(
                propagate_types_to_choice=[],
            ),
            fallback_configuration=ToolFallbackConfig(strategies=[ContinueStrategyModel()]),
            open_ai_tool=OpenAiToolConfig(
                function=OpenAiToolFunction(
                    name=f"{deployment.id.replace('-', '_')}_tool",
                    description=deployment.description or "",
                    parameters=OpenAiToolFunctionParameters(
                        type=JsonTypeEnum.object, properties={}, required=[]
                    ),
                )
            ),
        )

        properties: dict[str, Any] = {}
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

        if config and config.get("properties"):
            config_required = set(config.get("required", []))
            for param_name, param_details in config["properties"].items():
                logger.debug(f"Processing parameter: {param_name} with details: {param_details}")
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

        return output_tool

    async def get_basic_toolset_config(self, toolset_dial_id: str) -> ToolsetInfo | None:
        api_key = self.__api_key_provider.get()
        if api_key is None:
            raise RuntimeError("API-KEY must be set")
        async with DialCoreClient(api_key=api_key, base_url=self.__dial_settings.url) as dial_core:
            try:
                logger.debug(f"Getting toolset tool config for {toolset_dial_id}")
                info_dict = await dial_core.get_toolset_info(toolset_dial_id)
                return ToolsetInfo.model_validate(info_dict)
            except HTTPStatusError as e:
                logger.exception("Something went wrong during getting toolset %s", toolset_dial_id)
                if e.response.status_code == 404:
                    raise ToolsetNotFoundException(
                        toolset_id=toolset_dial_id,
                        details=f"{e.response.status_code} {getattr(e.response, 'reason_phrase', '')}",
                    )
                elif e.response.status_code == 403:
                    raise ToolsetForbiddenException(
                        toolset_id=toolset_dial_id,
                        details=f"{e.response.status_code} {getattr(e.response, 'reason_phrase', '')}",
                    )
                raise
