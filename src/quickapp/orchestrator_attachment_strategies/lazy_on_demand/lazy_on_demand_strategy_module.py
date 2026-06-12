import logging

from aidial_sdk.chat_completion import Message
from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider

from quickapp.core.agent import OrchestratorCapabilities
from quickapp.common import StagedBaseTool
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.abstract.chat_completion_recovery_policy import ChatCompletionRecoveryPolicy
from quickapp.common.abstract.tool_attachment_keep_policy import AttachmentKeepPolicy
from quickapp.common.abstract.tool_execution_history_policy import ToolExecutionHistoryPolicy
from quickapp.common.preview import preview_module
from quickapp.config.application import ApplicationConfig
from quickapp.config.orchestrator_attachment_strategy import LazyOnDemandAttachmentStrategy
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._attachment_get_content_injector import (
    _AttachmentGetContentInjector,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._gating import (
    should_enable_get_content_tool,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_history_policy import (
    _GetContentHistoryPolicy,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_keep_policy import (
    _GetContentKeepPolicy,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_recovery_policy import (
    _GetContentRecoveryPolicy,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_tool import (
    _GetContentTool,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._tool_configs import (
    render_get_content_tool_config,
)

logger = logging.getLogger(__name__)


def _is_active(app_config: ApplicationConfig) -> bool:
    return isinstance(app_config.orchestrator.attachment_strategy, LazyOnDemandAttachmentStrategy)


@preview_module
class LazyOnDemandStrategyModule(Module):
    """Wires the `internal_attachments_get_content` tool and its policies when
    ``OrchestratorConfig.attachment_strategy`` is a
    :class:`LazyOnDemandAttachmentStrategy`. Filtered out entirely when
    ``ENABLE_PREVIEW_FEATURES`` is unset.
    """

    def configure(self, binder: Binder) -> None:
        binder.bind(_GetContentTool, to=_GetContentTool, scope=request_scope)
        binder.bind(
            _AttachmentGetContentInjector,
            to=_AttachmentGetContentInjector,
            scope=request_scope,
        )
        binder.bind(_GetContentKeepPolicy, to=_GetContentKeepPolicy, scope=request_scope)

    @multiprovider
    def _provide_internal_tools(
        self,
        app_config: ApplicationConfig,
        messages: list[Message],
        get_content_builder: AssistedBuilder[_GetContentTool],
        orchestrator_capabilities: OrchestratorCapabilities,
    ) -> list[StagedBaseTool]:
        if not _is_active(app_config):
            return []
        if not should_enable_get_content_tool(
            app_config.contexts,
            messages,
            orchestrator_capabilities.input_attachment_types,
        ):
            return []
        rendered_tool_config = render_get_content_tool_config(
            list(orchestrator_capabilities.input_attachment_types or [])
        )
        return [
            get_content_builder.build(
                tool_config=rendered_tool_config,
                name=rendered_tool_config.open_ai_tool.function.name,
                description=rendered_tool_config.open_ai_tool.function.description,
                contexts=list(app_config.contexts),
            )
        ]

    @multiprovider
    def provide_message_transformers(
        self,
        app_config: ApplicationConfig,
        attachment_get_content_injector: _AttachmentGetContentInjector,
    ) -> list[MessagesTransformer]:
        if not _is_active(app_config):
            return []
        return [attachment_get_content_injector]

    @multiprovider
    def provide_tool_attachment_keep_policies(
        self,
        app_config: ApplicationConfig,
        get_content_keep_policy: _GetContentKeepPolicy,
    ) -> list[AttachmentKeepPolicy]:
        if not _is_active(app_config):
            return []
        return [get_content_keep_policy]

    @multiprovider
    def provide_tool_execution_history_policies(
        self, app_config: ApplicationConfig
    ) -> list[ToolExecutionHistoryPolicy]:
        if not _is_active(app_config):
            return []
        return [_GetContentHistoryPolicy()]

    @multiprovider
    def provide_chat_completion_recovery_policies(
        self, app_config: ApplicationConfig
    ) -> list[ChatCompletionRecoveryPolicy]:
        if not _is_active(app_config):
            return []
        return [_GetContentRecoveryPolicy()]
