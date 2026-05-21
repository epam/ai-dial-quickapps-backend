import copy

from aidial_sdk.chat_completion.request import StaticTool
from fastapi_injector import request_scope
from injector import Binder, Module, NoScope, ProviderOf, multiprovider, provider, singleton
from openai.lib.azure import AsyncAzureOpenAI

from quickapp.agent._attachment_filter import _AttachmentFilter
from quickapp.agent._chat_completion_config_builder import _ChatCompletionConfigBuilder
from quickapp.agent._messages_transformers import _AddSystemPromptTransformer
from quickapp.agent._orchestrator_deployment_initializer import (
    _OrchestratorDeploymentInitializer,
    _OrchestratorStaticToolsContext,
)
from quickapp.agent._prompt_providers import ConfigBasedPromptProvider
from quickapp.agent.agent_settings import AgentSettings
from quickapp.agent.assistant_invoker import AssistantInvoker
from quickapp.agent.models import OpenAiToolConfigDict
from quickapp.agent.orchestrator import Orchestrator
from quickapp.agent.orchestrator_capabilities import OrchestratorCapabilities
from quickapp.agent.orchestrator_deployment_cache_service import OrchestratorDeploymentCacheService
from quickapp.common import (
    DIAL_API_KEY,
    DIAL_BEARER,
    ORCHESTRATOR_AZURE_CLIENT,
    ForwardedHeaders,
    StagedBaseTool,
)
from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.abstract.base_transformer import MessagesTransformer, PreInvocationTransformer
from quickapp.common.abstract.chat_completion_recovery_policy import ChatCompletionRecoveryPolicy
from quickapp.common.abstract.tool_attachment_keep_policy import AttachmentKeepPolicy
from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.abstract.tool_execution_history_policy import ToolExecutionHistoryPolicy
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.chat_completion_recovery import ChatCompletionRecoveryService
from quickapp.common.chat_completion_stream.handler import ChatCompletionStreamHandler
from quickapp.common.dial_settings import DialSettings
from quickapp.common.stage_close_registry import DeferredStageCloseRegistry
from quickapp.common.state_holder import StateHolder
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.base import (
    BaseOpenAITool,
    ConfigurableSchemaArray,
    ConfigurableSchemaSimpleType,
    JsonSchemaConst,
    JsonSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
)
from quickapp.config.tools.display.paramenter import (
    FormattedParameterConfig,
    ParameterDisplayConfig,
)

DEFAULT_QUERY_PARAM = ConfigurableSchemaSimpleType(
    type=JsonTypeEnum.string,
    description="Query prompt to the tool",
    display=ParameterDisplayConfig(
        stage=FormattedParameterConfig(show_value_in_stage_title=True, name="**Prompt:** ")
    ),
)

DEFAULT_ATTACHMENT_URLS_PARAM = ConfigurableSchemaArray(
    type=JsonTypeEnum.array,
    description="A list of full URLs for each attachment related to the tool call. Each item must be a full URL string. *Always provide a list*, even if there is only one attachment. Do not provide a single string; use a list with one element instead. If there are no attachments, provide an empty list.",
    items=JsonSchemaSimpleType(type=JsonTypeEnum.string),
    display=ParameterDisplayConfig(stage=FormattedParameterConfig(name="**Files:** ")),
)


class AgentModule(Module):

    def configure(self, binder: Binder) -> None:
        # FIXME: mypy warning:
        binder.bind(Orchestrator, to=Orchestrator)  # type: ignore[type-abstract]
        binder.bind(StateHolder, to=StateHolder, scope=request_scope)
        binder.bind(
            DeferredStageCloseRegistry,
            to=DeferredStageCloseRegistry,
            scope=request_scope,
        )
        binder.bind(
            ChatCompletionRecoveryService,
            to=ChatCompletionRecoveryService,
            scope=request_scope,
        )
        binder.bind(AssistantInvoker, to=AssistantInvoker, scope=NoScope)
        binder.bind(_ChatCompletionConfigBuilder, to=_ChatCompletionConfigBuilder, scope=NoScope)
        binder.bind(ChatCompletionStreamHandler, to=ChatCompletionStreamHandler, scope=NoScope)
        binder.bind(_AttachmentFilter, to=_AttachmentFilter, scope=request_scope)
        binder.bind(
            _AddSystemPromptTransformer, to=_AddSystemPromptTransformer, scope=request_scope
        )
        binder.bind(AgentSettings, to=AgentSettings, scope=singleton)
        binder.bind(ConfigBasedPromptProvider, to=ConfigBasedPromptProvider, scope=request_scope)
        binder.bind(
            OrchestratorDeploymentCacheService,
            to=OrchestratorDeploymentCacheService,
            scope=singleton,
        )
        binder.bind(
            _OrchestratorDeploymentInitializer,
            to=_OrchestratorDeploymentInitializer,
            scope=request_scope,
        )
        binder.bind(
            _OrchestratorStaticToolsContext,
            to=_OrchestratorStaticToolsContext,
            scope=request_scope,
        )

    @multiprovider
    def _provide_completion_initializers(
        self, initializer_provider: ProviderOf[_OrchestratorDeploymentInitializer]
    ) -> list[CompletionInitializer]:
        return [initializer_provider.get()]

    @provider
    def provide_orchestrator_capabilities(
        self, initializer: _OrchestratorDeploymentInitializer
    ) -> OrchestratorCapabilities:
        return initializer.capabilities

    @provider
    def provide_openai_client(
        self,
        dial_settings: DialSettings,
        api_key: DIAL_API_KEY,
        config: ApplicationConfig,
        forwarded_headers: ForwardedHeaders,
        bearer: DIAL_BEARER,
    ) -> ORCHESTRATOR_AZURE_CLIENT:
        headers = dict(forwarded_headers or {})

        if bearer:
            headers["Authorization"] = f"Bearer {bearer.get_secret_value()}"

        azure_client = AsyncAzureOpenAI(
            azure_endpoint=dial_settings.url,
            api_key=api_key.get_secret_value(),
            azure_deployment=config.orchestrator.deployment.deployment_id,
            api_version=dial_settings.api_version,
            default_headers=headers,
        )
        return azure_client

    @multiprovider
    def provide_openai_tools(
        self, tools: list[StagedBaseTool], static_tools: list[StaticTool]
    ) -> list[OpenAiToolConfigDict]:
        openai_functions = []
        for tool in tools:
            if issubclass(type(tool.tool_config), BaseOpenAITool):
                open_ai_tool: OpenAiToolConfig = tool.tool_config.open_ai_tool
                open_ai_tool = self._remove_const_params(open_ai_tool)
                if tool.tool_config.type in [
                    "deployment-tool"
                ]:  # Append Query and attachment_urls for all deployment tools if they are missing.
                    open_ai_tool = self._append_default_props(open_ai_tool)
                openai_functions.append(open_ai_tool.model_dump(mode="json", exclude_none=True))
        for default_tool in static_tools:
            openai_functions.append(default_tool.model_dump(mode="json", exclude_none=True))
        return openai_functions

    @multiprovider
    def provide_static_tools(
        self, orchestrator_static_tools_context: _OrchestratorStaticToolsContext
    ) -> list[StaticTool]:
        return orchestrator_static_tools_context.static_tools

    @staticmethod
    def _remove_const_params(open_ai_tool):
        tool_copy = copy.deepcopy(open_ai_tool)
        props = tool_copy.function.parameters.properties

        for prop_name in list(props.keys()):
            if issubclass(type(props[prop_name]), JsonSchemaConst):
                del props[prop_name]

        return tool_copy

    @staticmethod
    def _append_default_props(converted_open_ai_tool: OpenAiToolConfig):
        if "query" not in converted_open_ai_tool.function.parameters.properties:
            converted_open_ai_tool.function.parameters.properties["query"] = DEFAULT_QUERY_PARAM
        if "attachment_urls" not in converted_open_ai_tool.function.parameters.properties:
            converted_open_ai_tool.function.parameters.properties["attachment_urls"] = (
                DEFAULT_ATTACHMENT_URLS_PARAM
            )
        return converted_open_ai_tool

    @multiprovider
    def provide_message_transformers(
        self,
        add_system_prompt: _AddSystemPromptTransformer,
    ) -> list[MessagesTransformer]:
        return [
            add_system_prompt,
        ]

    @multiprovider
    def provide_pre_invocation_transformers(
        self,
        attachment_filter: _AttachmentFilter,
    ) -> list[PreInvocationTransformer]:
        return [attachment_filter]

    @multiprovider
    def provide_chat_completion_recovery_policies(self) -> list[ChatCompletionRecoveryPolicy]:
        return []

    @multiprovider
    def provide_tool_execution_history_policies(self) -> list[ToolExecutionHistoryPolicy]:
        return []

    @multiprovider
    def provide_tool_attachment_keep_policies(self) -> list[AttachmentKeepPolicy]:
        return []

    @multiprovider
    def provide_tool_call_result_enrichers(self) -> list[ToolCallResultEnricher]:
        return []

    @multiprovider
    def provide_prompt_parts(
        self,
        config_prompt: ConfigBasedPromptProvider,
    ) -> list[PromptPartProvider]:
        return [config_prompt]
