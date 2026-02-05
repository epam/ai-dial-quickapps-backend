from typing import Any, Optional, cast

from injector import AssistedBuilder

from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.tools.deployment import ContentPropagation, DialDeploymentTool
from quickapp.dial_deployment_tooling.dial_completion_service import DialCompletionService

from .deployment_stage_wrapper import DeploymentStageWrapper
from ..common.utils import to_plain_dict


class BaseDeploymentTool(StagedBaseTool):

    def __init__(
        self,
        application_id: str,
        application_name: str,
        tool_config: DialDeploymentTool,
        content_propagation: Optional[ContentPropagation],
        dial_completion_service: DialCompletionService,
        perf_timer: PerformanceTimer,
        stage_wrapper_builder: AssistedBuilder[DeploymentStageWrapper],
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
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

    def _pre_process_params(self, **kwargs: Any) -> Any:

        if isinstance(self.tool_config, DialDeploymentTool):
            tool_config = cast(DialDeploymentTool, self.tool_config)
            # deployment and parameters are expected to be present on DialDeploymentTool

            params = tool_config.deployment.parameters
            params_dict = to_plain_dict(params)
            for key, value in params_dict.items():
                if key == "custom_fields":
                    cf = to_plain_dict(value)
                    if cf:
                        kwargs["custom_fields"] = cf
                    else:
                        # if custom_fields exists but is empty, set as empty dict to be explicit
                        kwargs["custom_fields"] = {}
                else:
                    kwargs[key] = value

        return kwargs
