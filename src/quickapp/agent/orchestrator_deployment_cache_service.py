from __future__ import annotations

from aidial_client.types.application import Application
from aidial_client.types.deployment import Deployment

from quickapp.common.cache import CacheService


class OrchestratorDeploymentCacheService(CacheService[Deployment | Application]):
    """
    Cross-request cache for raw DialCore deployment/application models used by the
    orchestrator path. Keys and instance are independent of
    :class:`quickapp.dial_deployment_tooling._di_types.DialDeploymentToolCacheService`.
    """
