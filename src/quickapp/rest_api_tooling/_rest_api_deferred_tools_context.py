from quickapp.common.deferred_tools_accumulator import DeferredToolsAccumulator


class _RestApiDeferredToolsContext(DeferredToolsAccumulator):
    """Request-scoped deferred-tool registry owned by REST API tooling."""
