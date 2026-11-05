from quickapp.common.deferred_tools_accumulator import DeferredToolsAccumulator


class _InternalDeferredToolsContext(DeferredToolsAccumulator):
    """Request-scoped deferred-tool registry owned by internal tooling."""
