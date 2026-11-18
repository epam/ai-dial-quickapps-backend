from aidial_client.types.application import Application
from aidial_client.types.deployment import Deployment


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
    def reasoning_efforts(self) -> list[str]:
        """The reasoning-effort values the deployment advertises, empty when it advertises none."""
        features = self._deployment.features
        return list(features.reasoning_efforts) if features else []

    def supports_reasoning_effort(self, reasoning_effort: str) -> bool:
        """Whether ``reasoning_effort`` is advertised by the deployment.

        An empty ``features.reasoningEfforts`` means no value is supported: a deployment
        that takes the parameter is expected to list the values it takes.
        """
        return reasoning_effort in self.reasoning_efforts

    @property
    def supports_temperature(self) -> bool:
        """Whether the deployment accepts a custom ``temperature``.

        Only an explicit ``false`` of ``features.temperature`` (Core ``temperatureSupported``)
        or ``features.custom_temperature_supported`` means no: Core defaults both flags to
        true, so an absent value is treated as supported.
        """
        features = self._deployment.features
        if features is None:
            return True
        return (
            features.temperature is not False and features.custom_temperature_supported is not False
        )

    @property
    def supports_cache_breakpoints(self) -> bool:
        """Whether the deployment advertises ``features.cache`` (Core ``cacheSupported``)."""
        features = self._deployment.features
        return features is not None and features.cache is True
