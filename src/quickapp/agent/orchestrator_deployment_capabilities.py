from __future__ import annotations

from aidial_client.types.application import Application
from aidial_client.types.deployment import Deployment

from quickapp.common.utils import matches_type


class OrchestratorDeploymentCapabilities:
    """
    Request-scoped DialCore metadata for the orchestrator deployment.

    Populated once per chat completion by :class:`._OrchestratorDeploymentInitializer`
    before tools and :class:`AssistantInvoker` run. If uninitialized (e.g. non-completion
    scopes), :meth:`orchestrator_accepts_mime_type` is conservative (deny).
    """

    def __init__(self) -> None:
        self._deployment_id: str | None = None
        self._input_attachment_types: list[str] | None = None
        self._deployment: Deployment | Application | None = None

    def populate_from_dial_model(self, model: Deployment | Application) -> None:
        self._deployment = model
        self._deployment_id = model.id
        self._input_attachment_types = model.input_attachment_types

    @property
    def deployment_id(self) -> str | None:
        return self._deployment_id

    @property
    def input_attachment_types(self) -> list[str] | None:
        return self._input_attachment_types

    @property
    def deployment(self) -> Deployment | Application | None:
        return self._deployment

    def orchestrator_accepts_mime_type(self, mime_type: str | None) -> bool:
        """Whether the orchestrator deployment accepts ``mime_type`` (DialCore patterns)."""
        return matches_type(mime_type, self._input_attachment_types)
