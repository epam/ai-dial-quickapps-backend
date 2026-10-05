from quickapp.common.deferred_tools_accumulator import DeferredToolsAccumulator


class _DeploymentDeferredToolsContext(DeferredToolsAccumulator):
    """Request-scoped deferred-tool registry owned by DIAL deployment tooling."""
