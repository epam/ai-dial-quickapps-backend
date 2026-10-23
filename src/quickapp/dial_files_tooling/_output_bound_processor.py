import re

from injector import inject

from quickapp.common.abstract.tool_call_result_processor import (
    ProcessingContext,
    ToolCallResultProcessor,
)
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.common.tool_names import INTERNAL_FILE_TOOL_NAME_PREFIX
from quickapp.dial_files_tooling._offload_config import ResolvedOffloadConfig
from quickapp.dial_files_tooling._utils import cap_output

# Floor of the backstop, deliberately above the per-tool caps (`MAX_OUTPUT_CHARS`): tools
# that bound their own output precisely are untouched, and well-behaved ones such as
# list/find keep their full result. When offload is enabled the effective limit is raised
# to its `size_threshold` (see `FileToolResultBoundProcessor`).
DEFAULT_MAX_RESULT_CHARS = 32_000

_OPENING_FENCE = re.compile(r"`{3,}")


class FileToolResultBoundProcessor(ToolCallResultProcessor):
    """Default-on guarantee that no ``internal_file_*`` result is unbounded.

    Applies by tool-name prefix, so a file tool added later is covered without anyone
    remembering to opt in. Runs after offload (``order=0``): whatever offload shrank or
    deliberately excluded (the read-back tools) still passes through here, as does the
    original text when an offload upload failed.
    """

    order = 10

    @inject
    def __init__(self, offload_config: ResolvedOffloadConfig) -> None:
        # N chars are >= N bytes, so a limit >= size_threshold never cuts what offload would
        # have taken; the floor keeps the default for small thresholds.
        self._max_chars = (
            max(DEFAULT_MAX_RESULT_CHARS, offload_config.size_threshold)
            if offload_config.enabled
            else DEFAULT_MAX_RESULT_CHARS
        )

    async def process(self, result: ToolCallResult, ctx: ProcessingContext) -> ToolCallResult:
        if not ctx.tool_name.startswith(INTERNAL_FILE_TOOL_NAME_PREFIX):
            return result
        capped, truncated = cap_output(result.content, self._max_chars)
        if not truncated:
            return result
        return result.model_copy(update={"content": self._with_notice(result.content, capped)})

    def _with_notice(self, original: str, capped: str) -> str:
        # list/find fence their output; keep the block closed so the rest of the
        # conversation does not render as code.
        fence = _OPENING_FENCE.match(original)
        closing = f"\n{fence.group()}" if fence else ""
        return (
            f"{capped}{closing}\n"
            f"-- output truncated at {self._max_chars} characters; "
            "request a smaller range or a narrower query --"
        )
