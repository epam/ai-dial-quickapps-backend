from typing import Any, Optional

from injector import AssistedBuilder

from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.config.tools.deployment import ContentPropagation, DialDeploymentTool
from quickapp.dial_deployment_tooling.dial_completion_service import DialCompletionService

from .deployment_stage_wrapper import DeploymentStageWrapper


class BaseDeploymentTool(StagedBaseTool):

    def __init__(
        self,
        application_id: str,
        application_name: str,
        tool_config: DialDeploymentTool,
        content_propagation: Optional[ContentPropagation],
        dial_completion_service: DialCompletionService,
        stage_wrapper_builder: AssistedBuilder[DeploymentStageWrapper],
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            **kwargs,
        )
        self.__application_id: str = application_id
        self.__application_name: str = application_name
        self.__dial_completion_service: DialCompletionService = dial_completion_service
        self.__content_propagation: Optional[ContentPropagation] = content_propagation

    async def _run_in_stage_async(
        self,
        stage_wrapper: Optional[BaseStageWrapper],
        attachment_urls: Optional[list[str]] = None,
        **kwargs,
    ) -> CompletionResult:
        return await self.__dial_completion_service.complete_request_async(
            kwargs,
            self.__application_id,
            self.__application_name,
            self.__content_propagation,
            stage_wrapper,
            attachment_urls,
        )
