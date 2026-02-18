import logging
from typing import Any, Optional

from injector import AssistedBuilder, inject

from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.tools.internal import InternalTool
from quickapp.skills._skill_reader_stage_wrapper import _SkillReaderStageWrapper
from quickapp.skills.agent_skills_provider import AgentSkillsProvider

logger = logging.getLogger(__name__)


@inject
class _SkillReaderTool(StagedBaseTool):
    """Internal tool that reads skill file content and returns it."""

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_SkillReaderStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        skills_provider: AgentSkillsProvider,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            **kwargs,
        )
        self.__skills_provider = skills_provider

    async def _run_in_stage_async(
        self,
        stage_wrapper: Optional[BaseStageWrapper] = None,
        skill_name: Optional[str] = None,
        *args: Any,
        **kwargs: Any,
    ) -> CompletionResult:
        """Execute the skill reader tool."""
        if not skill_name:
            error_msg = "Missing required parameter: skill_name"
            logger.error(error_msg)
            result = CompletionResult(content=error_msg, content_type="text/plain")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result

        try:
            content = self.__skills_provider.get_skill_content(skill_name)
            result = CompletionResult(content=content, content_type="text/markdown")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result
        except FileNotFoundError as e:
            error_msg = f"Error: {str(e)}"
            logger.warning(error_msg)
            result = CompletionResult(content=error_msg, content_type="text/plain")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result
        except ValueError as e:
            error_msg = f"Error: {str(e)}"
            logger.warning(error_msg)
            result = CompletionResult(content=error_msg, content_type="text/plain")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result
        except Exception as e:
            error_msg = f"Error reading skill file: {str(e)}"
            logger.error(error_msg, exc_info=True)
            result = CompletionResult(content=error_msg, content_type="text/plain")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result
