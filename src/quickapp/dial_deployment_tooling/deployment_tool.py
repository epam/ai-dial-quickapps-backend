import re
from typing import Optional

from injector import AssistedBuilder, inject
from pydantic import BaseModel, Field

from quickapp.config.tools.deployment import ContentPropagation, DialDeploymentTool

from .base_deployment_tool import BaseDeploymentTool
from .deployment_stage_wrapper import DeploymentStageWrapper
from .dial_completion_service import DialCompletionService

_VALID_NAME_PATTERN: re.Pattern[str] = re.compile(r"[^a-zA-Z0-9_.-]")


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
        stage_wrapper_builder: AssistedBuilder[DeploymentStageWrapper],
    ):
        sanitized_tool_name = sanitize_string(application_name)
        super().__init__(
            application_id=application_id,
            application_name=application_name,
            content_propagation=content_propagation,
            dial_completion_service=dial_completion_service,
            tool_config=tool_config,
            stage_wrapper_builder=stage_wrapper_builder,
            name=sanitized_tool_name,
            description=description,
        )
        self.stage_name_component = f"Calling {sanitized_tool_name} application"


def sanitize_string(input_str: str) -> str:
    """
    Sanitizes a string to match the pattern ^[a-zA-Z0-9_-]{1,64}$

    Args:
        input_str: Input string to sanitize

    Returns:
        Sanitized string containing only allowed characters (a-z, A-Z, 0-9, _, -)
        with length 1-64 characters. Returns empty string if no valid characters exist.
    """
    # Step 1: Remove all invalid characters
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '', input_str)

    # Step 2: Truncate to max 64 characters
    sanitized = sanitized[:64]

    return sanitized
