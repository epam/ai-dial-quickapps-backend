from aidial_client.types.application import Application
from aidial_client.types.deployment import Deployment

from quickapp.common.utils import matches_type


class OrchestratorCapabilities:
    """Request-scoped DialCore metadata for the orchestrator deployment.

    Wraps a populated :class:`Deployment` or :class:`Application`; production
    instances are built once per chat completion and exposed via DI from
    :class:`AgentModule`.
    """

    def __init__(
        self,
        deployment: Deployment | Application,
        *,
        app_accepted_types: list[str] | None = None,
    ) -> None:
        self._deployment: Deployment | Application = deployment
        self._app_accepted_types: list[str] | None = app_accepted_types

    @property
    def deployment_id(self) -> str:
        return self._deployment.id

    @property
    def input_attachment_types(self) -> list[str] | None:
        return self._deployment.input_attachment_types

    @property
    def advertised_input_attachment_types(self) -> list[str] | None:
        """The allowlist to advertise to the model: the app's own ``accepted_types``
        (``LazyOnDemandAttachmentStrategy.accepted_types``) verbatim when set — it is
        the narrower intent by construction — otherwise the deployment's declared
        ``input_attachment_types``. Deliberately not filtered against the deployment's
        list here: correctly deciding whether two MIME *patterns* (e.g. ``image/*`` vs
        a deployment's concrete ``image/png``) overlap is exactly the fiddly pattern-
        intersection problem :meth:`orchestrator_accepts_mime_type` avoids by checking
        concrete mimes against both lists instead."""
        if self._app_accepted_types is not None:
            return self._app_accepted_types
        return self.input_attachment_types

    def orchestrator_accepts_mime_type(self, mime_type: str | None) -> bool:
        """Whether the orchestrator deployment accepts ``mime_type`` (DialCore patterns),
        narrowed by the app's own ``accepted_types`` when configured. A mime must match
        *both* lists (conjunction, not an intersected pattern set) — the deployment
        remains a hard cap that the app can only narrow, never widen."""
        if not matches_type(mime_type, self.input_attachment_types):
            return False
        if self._app_accepted_types is not None and not matches_type(
            mime_type, self._app_accepted_types
        ):
            return False
        return True

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
