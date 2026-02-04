import copy

from fastapi_injector import request_scope
from injector import Binder, Module, NoScope, multiprovider, provider, singleton
from openai import AsyncAzureOpenAI

from quickapp.common import AgentSkillsProvider
from quickapp.agent.assistant_invoker import AssistantInvoker
from quickapp.agent.models import OpenAiToolConfigDict
from quickapp.agent.orchestrator import Orchestrator
from quickapp.agent.processors.chunk_processor import ChunkProcessor
from quickapp.agent.processors.pre_transformers import (
    AddContextAttachmentTransformer,
    AddSystemPromptTransformer,
    AttachmentNotificationInjector,
    ExtractToolCallsFromStateProcessor,
    PreTransformer,
    ReduceAttachmentTransformer,
)
from quickapp.common import DIAL_API_KEY, StagedBaseTool
from quickapp.common.dial_settings import DialSettings
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.state_holder import StateHolder
from quickapp.common.utils import sanitize_toolname
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
from quickapp.internal_tooling.attachment_notification_tooling._tool_configs import (
    AVAILABLE_CONTEXT_TOOL_NAME,
    should_activate_context_tool,
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
        binder.bind(ChunkProcessor, to=ChunkProcessor, scope=NoScope)
        binder.bind(AgentSkillsProvider, to=AgentSkillsProvider, scope=singleton)

    @provider
    def provide_openai_client(
        self,
        dial_settings: DialSettings,
        api_key: DIAL_API_KEY,
        config: ApplicationConfig,
    ) -> AsyncAzureOpenAI:
        azure_client = AsyncAzureOpenAI(
            azure_endpoint=dial_settings.url,
            api_key=api_key.get_secret_value(),
            azure_deployment=config.orchestrator.deployment.name,
            api_version=dial_settings.api_version,
        )
        return azure_client

    @multiprovider
    def provide_pre_processors(
        self,
        config: ApplicationConfig,
        messages_context: MessagesMixin,
        agent_skills_provider: AgentSkillsProvider,
    ) -> list[PreTransformer]:
        # Order of Transformers is crucial for correct request processing
        transformers: list[PreTransformer] = [
            AddSystemPromptTransformer(
                config.orchestrator.system_prompt.content, agent_skills_provider.get_skills_xml()
            ),
            ExtractToolCallsFromStateProcessor(),
            ReduceAttachmentTransformer(),
            AddContextAttachmentTransformer(config.contexts),
        ]
        if should_activate_context_tool(config.contexts, messages_context.messages):
            transformers.append(
                AttachmentNotificationInjector(
                    context_tool_name=AVAILABLE_CONTEXT_TOOL_NAME,
                    contexts=config.contexts,
                )
            )
        return transformers

    @multiprovider
    def provide_openai_tools(self, tools: list[StagedBaseTool]) -> list[OpenAiToolConfigDict]:
        openai_functions = []
        for tool in tools:
            if issubclass(type(tool.tool_config), BaseOpenAITool):
                open_ai_tool: OpenAiToolConfig = tool.tool_config.open_ai_tool
                open_ai_tool.function.name = sanitize_toolname(open_ai_tool.function.name)
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
