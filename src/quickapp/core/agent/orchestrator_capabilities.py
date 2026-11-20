from aidial_client.types.application import Application
from aidial_client.types.deployment import Deployment, Features


class OrchestratorCapabilities:
    """Request-scoped DialCore metadata for the orchestrator deployment.

    Wraps a populated :class:`Deployment` or :class:`Application`; production
    instances are built once per chat completion and exposed via DI from
    :class:`AgentModule`.
    """

    def __init__(self, deployment: Deployment | Application) -> None:
        self._deployment: Deployment | Application = deployment

    @property
    def deployment_id(self) -> str:
        return self._deployment.id

    @property
    def input_attachment_types(self) -> list[str] | None:
        return self._deployment.input_attachment_types

    @property
    def features(self) -> Features:
        """The deployment's features, or an empty ``Features`` when it reports none."""
        return self._deployment.features or Features()

    @property
    def supports_cache_breakpoints(self) -> bool:
        """Whether the deployment advertises ``features.cache`` (Core ``cacheSupported``)."""
        features = self._deployment.features
        return features is not None and features.cache is True
