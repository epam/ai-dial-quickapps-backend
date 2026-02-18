from typing import Optional

from aidial_sdk.chat_completion import Message
from injector import AssistedBuilder, inject
from pydantic import BaseModel, Field

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
        content_propagation: Optional[ContentPropagation],
        dial_completion_service: DialCompletionService,
        messages: list[Message],
        stage_wrapper_builder: AssistedBuilder[DeploymentStageWrapper],
        perf_timer: PerformanceTimer,
    ):
        super().__init__(
            application_id=application_id,
            application_name=application_name,
            content_propagation=content_propagation,
            dial_completion_service=dial_completion_service,
            messages=messages,
            tool_config=tool_config,
            stage_wrapper_builder=stage_wrapper_builder,
            description=description,
            perf_timer=perf_timer,
        )
        self.stage_name_component = f"Calling {application_name} application"
