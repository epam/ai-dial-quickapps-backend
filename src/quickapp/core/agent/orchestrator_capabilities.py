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
