from typing import Any

from injector import AssistedBuilder, inject

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.deployment_usage import DeploymentUsage
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.tool_allowlist import ToolAllowlist
from quickapp.config.application import StageDisplayLevel
from quickapp.config.tools.internal import InternalTool

from ._task_runner import TaskRunner
from ._task_stage_wrapper import _TaskStageWrapper
from ._tool_catalogue import IMPLICIT_TASK_TOOL_NAMES, _DelegableToolNames
from ._tool_config import INHERIT_TOOLS, is_inherit

# Keeps the unknown-tool error readable for apps with large MCP catalogues.
_MAX_LISTED_TOOL_NAMES = 60


def _listing(names: list[str]) -> str:
    if not names:
        return "(none)"
    shown = ", ".join(names[:_MAX_LISTED_TOOL_NAMES])
    hidden = len(names) - _MAX_LISTED_TOOL_NAMES
    return f"{shown}, ...and {hidden} more" if hidden > 0 else shown


@inject
class _RunTaskTool(StagedBaseTool):
    """``internal_run_task`` — run a self-contained task and return its final answer."""

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_TaskStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        runner: TaskRunner,
        delegable_tools: _DelegableToolNames,
        stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            stage_display_level=stage_display_level,
            **kwargs,
        )
        self.__runner = runner
        self.__delegable_tools = delegable_tools

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        tool_call_id: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        _require_text(kwargs, "name", "A short task label is required.")
        prompt = _require_text(kwargs, "prompt", "A task description is required.")
        allowlist = self.__resolve_allowlist(kwargs.get("tools"))

        task = await self.__runner.run(prompt, allowlist, stage_wrapper)

        result = ToolCallResult(
            content=task.answer,
            content_type="text/markdown",
            attachments=task.attachments or None,
            usage=self.__as_task_usage(task.usage) or None,
        )
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result

    def __as_task_usage(self, usage: list[DeploymentUsage]) -> list[DeploymentUsage]:
        """The task's own model calls get a row under the tool's name, not the agent's."""
        return [
            (
                row.model_copy(
                    update={
                        "deployment_name": self._resolve_tool_name(),
                        "deployment_id": row.model_name,
                    }
                )
                if row.is_orchestrator()
                else row
            )
            for row in usage
        ]

    def __resolve_allowlist(self, tools: Any) -> ToolAllowlist:
        """The task's allowlist; unknown names fail the call rather than being dropped.

        A task quietly running with fewer tools than intended does not error — it
        answers from the prompt alone. The message names the valid options so the
        LLM can retry.
        """
        if is_inherit(tools):
            return ToolAllowlist()
        if not isinstance(tools, list) or not all(isinstance(name, str) for name in tools):
            raise InvalidToolCallParameterException(
                parameter_name="tools",
                message=f'Expected ["{INHERIT_TOOLS}"] or a list of tool names.',
            )
        if INHERIT_TOOLS in tools:
            raise InvalidToolCallParameterException(
                parameter_name="tools",
                message=f'"{INHERIT_TOOLS}" must be the only item. Pass ["{INHERIT_TOOLS}"] '
                "for every tool, or a list of tool names.",
            )
        available = self.__delegable_tools.names()
        unknown = sorted(set(tools) - set(available))
        if unknown:
            raise InvalidToolCallParameterException(
                parameter_name="tools",
                message=(
                    f"Unknown tools: {', '.join(unknown)}. "
                    f'Pass ["{INHERIT_TOOLS}"] or pick from: {_listing(available)}.'
                ),
            )
        return ToolAllowlist(names=frozenset(tools) | IMPLICIT_TASK_TOOL_NAMES)


def _require_text(kwargs: dict[str, Any], parameter: str, message: str) -> str:
    value = kwargs.get(parameter)
    if not isinstance(value, str) or not value.strip():
        raise InvalidToolCallParameterException(parameter_name=parameter, message=message)
    return value
