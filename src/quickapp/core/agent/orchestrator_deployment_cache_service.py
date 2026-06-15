from collections.abc import Awaitable, Callable

from aidial_client.types.application import Application
from aidial_client.types.deployment import Deployment

from quickapp.common.cache import CacheService
from quickapp.common.exceptions import OrchestratorInitializationException

_ORCHESTRATOR_DEPLOYMENT_CACHE_KEY_PREFIX = "orchestrator_deployment_"


class OrchestratorDeploymentCacheService(CacheService[Deployment | Application]):
    """Cache for orchestrator deployment metadata.

    Held separately from :class:`DialDeploymentToolCacheService` so that orchestrator
    capability lookups can evict independently of deployment-tool config caching, and
    so neither path can starve the other on TTL renewal.
    """

    async def fetch_metadata(
        self,
        loader: Callable[[str], Awaitable[Deployment | Application | None]],
        deployment_id: str,
    ) -> Deployment | Application:
        model = await self.get(
            f"{_ORCHESTRATOR_DEPLOYMENT_CACHE_KEY_PREFIX}{deployment_id}",
            loader,
            deployment_id,
        )
        if model is None:
            raise OrchestratorInitializationException(
                message="No deployment metadata returned",
                deployment_id=deployment_id,
            )
        return model
