import logging

from aidial_sdk.chat_completion import Message
from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider

from quickapp.agent.orchestrator_deployment_capabilities import OrchestratorDeploymentCapabilities
from quickapp.attachment_processing._attachment_notification_injector import (
    _AttachmentNotificationInjector,
)
from quickapp.attachment_processing._available_context_tool import _AvailableContextTool
from quickapp.attachment_processing._context_entries import (
    should_activate_context_tool,
    should_enable_lazy_context_fetch_tool,
)
from quickapp.attachment_processing._get_context_tool import _GetContextTool
from quickapp.attachment_processing._tool_configs import (
    AVAILABLE_CONTEXT_TOOL_CONFIG,
    GET_CONTENT_TOOL_CONFIG,
)
from quickapp.common import StagedBaseTool
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.config.application import ApplicationConfig

logger = logging.getLogger(__name__)


class AttachmentProcessingModule(Module):
    def configure(self, binder: Binder) -> None:
        binder.bind(_AvailableContextTool, to=_AvailableContextTool, scope=request_scope)
        binder.bind(_GetContextTool, to=_GetContextTool, scope=request_scope)
        binder.bind(
            _AttachmentNotificationInjector,
            to=_AttachmentNotificationInjector,
            scope=request_scope,
        )

        logger.debug("AttachmentProcessingModule module configuration completed")

    @multiprovider
    def _provide_internal_tools(
        self,
        app_config: ApplicationConfig,
        messages: list[Message],
        ac_builder: AssistedBuilder[_AvailableContextTool],
        get_content_builder: AssistedBuilder[_GetContextTool],
        orchestrator_capabilities: OrchestratorDeploymentCapabilities,
    ) -> list[StagedBaseTool]:
        tools: list[StagedBaseTool] = []

        if should_activate_context_tool(app_config.contexts, messages):
            tools.append(
                ac_builder.build(
                    tool_config=AVAILABLE_CONTEXT_TOOL_CONFIG,
                    name=AVAILABLE_CONTEXT_TOOL_CONFIG.open_ai_tool.function.name,
                    description=AVAILABLE_CONTEXT_TOOL_CONFIG.open_ai_tool.function.description,
                    contexts=list(app_config.contexts),
                )
            )
            if should_enable_lazy_context_fetch_tool(
                app_config.contexts,
                orchestrator_capabilities.input_attachment_types,
            ):
                tools.append(
                    get_content_builder.build(
                        tool_config=GET_CONTENT_TOOL_CONFIG,
                        name=GET_CONTENT_TOOL_CONFIG.open_ai_tool.function.name,
                        description=GET_CONTENT_TOOL_CONFIG.open_ai_tool.function.description,
                        contexts=list(app_config.contexts),
                    )
                )

        return tools

    @multiprovider
    def provide_message_transformers(
        self,
        attachment_notification_injector: _AttachmentNotificationInjector,
    ) -> list[MessagesTransformer]:
        return [attachment_notification_injector]
