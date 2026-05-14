from aidial_client.types.application import Application
from aidial_client.types.deployment import Deployment

from quickapp.common.utils import matches_type


class OrchestratorCapabilities:
    """
    Request-scoped DialCore metadata for the orchestrator deployment.

    Constructed with a populated :class:`Deployment` or :class:`Application`;
    there is no half-initialized state. Production instances are built by
    :class:`quickapp.agent._OrchestratorDeploymentInitializer` once per chat
    completion and exposed via the ``provide_orchestrator_capabilities``
    DI provider in :class:`AgentModule`.
    """

    def __init__(self, deployment: Deployment | Application) -> None:
        self._deployment: Deployment | Application = deployment

    @property
    def deployment_id(self) -> str:
        return self._deployment.id

    @property
    def input_attachment_types(self) -> list[str] | None:
        return self._deployment.input_attachment_types

    def orchestrator_accepts_mime_type(self, mime_type: str | None) -> bool:
        """Whether the orchestrator deployment accepts ``mime_type`` (DialCore patterns)."""
        return matches_type(mime_type, self.input_attachment_types)
