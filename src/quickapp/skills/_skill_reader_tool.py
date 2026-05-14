import logging
from typing import Any

from injector import AssistedBuilder, inject

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.tools.internal import InternalTool
from quickapp.skills._skill_reader_stage_wrapper import _SkillReaderStageWrapper
from quickapp.skills._skills_registry import SkillsRegistry

logger = logging.getLogger(__name__)


@inject
class _SkillReaderTool(StagedBaseTool):
    """Internal tool that reads skill file content and returns it."""

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_SkillReaderStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        skills_registry: SkillsRegistry,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            argument_transformers=argument_transformers,
            **kwargs,
        )
        self.__skills_registry = skills_registry

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        tool_call_id: str | None = None,
        skill_name: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        """Execute the skill reader tool."""
        if not skill_name:
            error_msg = "Missing required parameter: skill_name"
            logger.error(error_msg)
            result = ToolCallResult(content=error_msg, content_type="text/plain")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result

        try:
            content = self.__skills_registry.get_skill_content(skill_name)
            result = ToolCallResult(content=content, content_type="text/markdown")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result
        except FileNotFoundError as e:
            error_msg = f"Error: {str(e)}"
            logger.warning(error_msg)
            result = ToolCallResult(content=error_msg, content_type="text/plain")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result
        except ValueError as e:
            error_msg = f"Error: {str(e)}"
            logger.warning(error_msg)
            result = ToolCallResult(content=error_msg, content_type="text/plain")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result
        except Exception as e:
            error_msg = f"Error reading skill file: {str(e)}"
            logger.error(error_msg, exc_info=True)
            result = ToolCallResult(content=error_msg, content_type="text/plain")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result
