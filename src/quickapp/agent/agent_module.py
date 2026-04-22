import copy

from fastapi_injector import request_scope
from injector import Binder, Module, NoScope, multiprovider, provider, singleton
from openai.lib.azure import AsyncAzureOpenAI

from quickapp.agent._attachment_filter import _AttachmentFilter
from quickapp.agent._messages_transformers import _AddSystemPromptTransformer
from quickapp.agent._prompt_providers import ConfigBasedPromptProvider
from quickapp.agent.agent_settings import AgentSettings
from quickapp.agent.assistant_invoker import AssistantInvoker
from quickapp.agent.models import OpenAiToolConfigDict
from quickapp.agent.orchestrator import Orchestrator
from quickapp.common import (
    DIAL_API_KEY,
    ORCHESTRATOR_AZURE_CLIENT,
    ForwardedHeaders,
    StagedBaseTool,
)
from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.abstract.base_transformer import MessagesTransformer, PreInvocationTransformer
from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.chat_completion_stream.handler import ChatCompletionStreamHandler
from quickapp.common.dial_settings import DialSettings
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
        binder.bind(AssistantInvoker, to=AssistantInvoker, scope=NoScope)
        binder.bind(ChatCompletionStreamHandler, to=ChatCompletionStreamHandler, scope=NoScope)
        binder.bind(_AttachmentFilter, to=_AttachmentFilter, scope=request_scope)
        binder.bind(
            _AddSystemPromptTransformer, to=_AddSystemPromptTransformer, scope=request_scope
        )
        binder.bind(AgentSettings, to=AgentSettings, scope=singleton)
        binder.bind(ConfigBasedPromptProvider, to=ConfigBasedPromptProvider, scope=request_scope)

    @provider
    def provide_openai_client(
        self,
        dial_settings: DialSettings,
        api_key: DIAL_API_KEY,
        config: ApplicationConfig,
        forwarded_headers: ForwardedHeaders,
    ) -> ORCHESTRATOR_AZURE_CLIENT:
        azure_client = AsyncAzureOpenAI(
            azure_endpoint=dial_settings.url,
            api_key=api_key.get_secret_value(),
            azure_deployment=config.orchestrator.deployment.name,
            api_version=dial_settings.api_version,
            default_headers=forwarded_headers or None,
        )
        return azure_client

    @multiprovider
    def provide_openai_tools(self, tools: list[StagedBaseTool]) -> list[OpenAiToolConfigDict]:
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
        return openai_functions

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
    def provide_tool_call_result_enrichers(self) -> list[ToolCallResultEnricher]:
        return []

    @multiprovider
    def provide_prompt_parts(
        self,
        config_prompt: ConfigBasedPromptProvider,
    ) -> list[PromptPartProvider]:
        return [config_prompt]
