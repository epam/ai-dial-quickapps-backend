from injector import inject

from quickapp.common.abstract.tool_call_result_processor import (
    ProcessingContext,
    ToolCallResultProcessor,
)
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.config.tool_result_limit import ToolResultLimitSettings


class ToolCallResultSizeLimitProcessor(ToolCallResultProcessor):
    """Default-on guard that keeps an oversized tool response out of the LLM context.

    Applies to every tool. A result longer than ``max_chars``
    (``TOOL_CALL_RESULT_LIMIT__MAX_CHARS``) is replaced by an error telling the model the
    response was too large; the content is not passed on. Config validation keeps every offload
    ``size_threshold`` at or below the limit, so a result offload would have saved is never
    rejected here. Runs after offload (``order=10``): whatever offload shrank is small and passes
    through, while a result that offload skipped (disabled, excluded tool, read-back tools) or
    failed to upload is caught here.
    """

    order = 10

    @inject
    def __init__(self, settings: ToolResultLimitSettings) -> None:
        self._max_chars = settings.max_chars

    async def process(self, result: ToolCallResult, ctx: ProcessingContext) -> ToolCallResult:
        size = len(result.content)
        if size <= self._max_chars:
            return result
        return result.model_copy(
            update={
                "content": self._too_large_error(ctx.tool_name, size),
                "content_type": "text/plain",
            }
        )

    def _too_large_error(self, tool_name: str, size: int) -> str:
        return (
            f"Error: the call to '{tool_name}' completed, but its response is too large "
            f"({size} characters, the limit is {self._max_chars}) and was not returned. "
            "If the data is needed, request less of it: a smaller range, a narrower query "
            "or fewer fields."
        )
