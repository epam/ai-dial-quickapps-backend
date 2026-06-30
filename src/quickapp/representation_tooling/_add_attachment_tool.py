from typing import Any

from aidial_sdk.chat_completion import Attachment
from injector import AssistedBuilder, inject

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.application import StageDisplayLevel
from quickapp.config.tools.internal import InternalTool
from quickapp.representation_tooling._add_attachment_stage_wrapper import _AddAttachmentStageWrapper

_DEFAULT_ATTACHMENT_TYPE = "text/plain"


@inject
class _AddAttachmentTool(StagedBaseTool):

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_AddAttachmentStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            stage_display_level=stage_display_level,
            argument_transformers=argument_transformers,
            **kwargs,
        )

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        tool_call_id: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        url: str = kwargs["url"]
        title: str | None = kwargs.get("title")
        mime_type: str = kwargs.get("type") or _DEFAULT_ATTACHMENT_TYPE

        attachment = Attachment(url=url, title=title, type=mime_type)

        result = ToolCallResult(
            content=f"Attachment added to response: {title or url}",
            content_type="text/plain",
            attachments=[attachment],
            propagate_to_choice=[attachment],
        )
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
