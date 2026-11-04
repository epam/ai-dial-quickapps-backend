from quickapp.common import StagedBaseTool
from quickapp.common.deferred_tools_accumulator import DeferredToolsAccumulator


class _InternalDeferredToolsContext(DeferredToolsAccumulator):
    """Request-scoped deferred-tool registry owned by internal tooling.

    Also memoizes the built tools: the `list[StagedBaseTool]` provider is unscoped and
    re-runs on every injection, so the tools (and their deferred registration) are built
    once per request here.
    """

    def __init__(self) -> None:
        super().__init__()
        self.built_tools: list[StagedBaseTool] | None = None
