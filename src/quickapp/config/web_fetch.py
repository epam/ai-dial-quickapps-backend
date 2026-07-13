from pydantic import BaseModel, Field

from quickapp.config.dial_files import ToolCallResultOffloadSettings


class WebFetchConfig(BaseModel):
    """Per-app config for the built-in ``internal_web_fetch`` tool.

    Toggled by the explicit ``enabled`` flag. ``max_inline_size`` caps how much
    decoded text the tool returns inline; larger textual content is truncated to
    fit under the cap (head + notice). The cap's default is drawn from the same
    env setting that governs the offload threshold's default
    (``TOOL_CALL_RESULT_OFFLOAD__SIZE_THRESHOLD``), so out of the box the inline
    cap and the global offload threshold are equal — anything returned inline is
    below the offloader's trigger. See docs/designs/web_fetch_tool.md (Component
    4a) for the cases where an operator intentionally decouples the two.
    """

    enabled: bool = Field(
        default=False,
        description="Whether to expose the internal_web_fetch tool to the LLM.",
    )
    max_inline_size: int = Field(
        default_factory=lambda: ToolCallResultOffloadSettings().size_threshold,
        gt=0,
        description=(
            "Byte cap on the decoded text internal_web_fetch returns inline. "
            "Larger textual resources are truncated to fit under the cap, with a "
            "notice stating the total size and pointing at save_path; binary "
            "resources are rejected with guidance to re-call with a save_path. "
            "Defaults to the TOOL_CALL_RESULT_OFFLOAD__SIZE_THRESHOLD env var so "
            "the inline cap matches the global offload threshold by default."
        ),
    )
