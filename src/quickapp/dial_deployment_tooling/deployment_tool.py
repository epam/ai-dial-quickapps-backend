from injector import AssistedBuilder, inject
from pydantic import BaseModel, Field

from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.tools.deployment import ContentPropagation, DialDeploymentTool

from .base_deployment_tool import BaseDeploymentTool
from .deployment_stage_wrapper import DeploymentStageWrapper
from .dial_completion_service import DialCompletionService


class _DeploymentCompletionRequestInput(BaseModel):
    query: str = Field(description="Message parameter to send to the application")


@inject
class DeploymentTool(BaseDeploymentTool):

    def __init__(
        self,
        application_id: str,
        application_name: str,
        description: str,
        tool_config: DialDeploymentTool,
        content_propagation: ContentPropagation | None,
        dial_completion_service: DialCompletionService,
        messages_mixin: MessagesMixin,
        stage_wrapper_builder: AssistedBuilder[DeploymentStageWrapper],
        perf_timer: PerformanceTimer,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
    ):
        super().__init__(
            application_id=application_id,
            application_name=application_name,
            content_propagation=content_propagation,
            dial_completion_service=dial_completion_service,
            messages_mixin=messages_mixin,
            tool_config=tool_config,
            stage_wrapper_builder=stage_wrapper_builder,
            description=description,
            perf_timer=perf_timer,
            argument_transformers=argument_transformers,
        )
        self.stage_name_component = f"Calling {application_name} application"
