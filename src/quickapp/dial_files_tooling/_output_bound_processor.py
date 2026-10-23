from injector import inject

from quickapp.common.abstract.tool_call_result_processor import (
    ProcessingContext,
    ToolCallResultProcessor,
)
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.dial_files_tooling._offload_config import ResolvedOffloadConfig

# Far above the per-tool caps (`MAX_OUTPUT_CHARS`): tools that bound their own output
# precisely are untouched, and well-behaved ones such as list/find keep their full result.
MAX_RESULT_CHARS = 80_000


class ToolCallResultSizeLimitProcessor(ToolCallResultProcessor):
    """Default-on guard that keeps an oversized tool response out of the LLM context.

    Applies to every tool. A result over the limit is replaced by an error telling the model
    the response was too large; the content is not passed on. The limit is
    ``MAX_RESULT_CHARS``, raised to the offload ``size_threshold`` while offload is enabled, so
    a result offload would have saved is never rejected here. Runs after offload
    (``order=10``): whatever offload shrank is small and passes through, while a result that
    offload skipped (excluded tool, read-back tools) or failed to upload is caught here.
    """

    order = 10

    @inject
    def __init__(self, offload_config: ResolvedOffloadConfig) -> None:
        # N chars take >= N bytes, so a limit >= size_threshold only rejects results that
        # offload (which triggers at size_threshold bytes) would have taken.
        self._max_chars = (
            max(MAX_RESULT_CHARS, offload_config.size_threshold)
            if offload_config.enabled
            else MAX_RESULT_CHARS
        )

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
