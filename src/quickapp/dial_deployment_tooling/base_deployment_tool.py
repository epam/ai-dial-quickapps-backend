from typing import Any, Optional, cast

from injector import AssistedBuilder

from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.utils import to_plain_dict
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

        prepared: dict[str, Any] = {}

        # If tool config defines defaults, normalize them first
        if isinstance(self.tool_config, DialDeploymentTool):
            tool_config = cast(DialDeploymentTool, self.tool_config)
            params = tool_config.deployment.parameters
            params_dict = to_plain_dict(params)
            if isinstance(params_dict, dict):
                for key, value in params_dict.items():
                    # skip empty values
                    if value is None or value == {}:
                        continue
                    if key == "custom_fields":
                        if isinstance(value, dict):
                            configuration = value.get("configuration")
                            if isinstance(configuration, dict) and configuration:
                                for ck, cv in configuration.items():
                                    prepared[ck] = cv
                            # else ignore explicit empty custom_fields
                    else:
                        prepared[key] = value

        for key, value in kwargs.items():
            # Normalize each runtime value (Pydantic models -> plain dicts)
            normalized = to_plain_dict(value)
            # Skip empty values (None or empty dict/list)
            if normalized is None or normalized == {}:
                continue
            # unpack custom_fields.configuration if present, they should be merged into top-level parameters
            if key == "custom_fields" and isinstance(normalized, dict):
                configuration = normalized.get("configuration")
                if isinstance(configuration, dict) and configuration:
                    for ck, cv in configuration.items():
                        prepared[ck] = cv
            else:
                prepared[key] = normalized

        return prepared
