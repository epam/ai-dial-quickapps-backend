from quickapp.common.utils import matches_type
from quickapp.core.agent import OrchestratorCapabilities


class _AttachmentAcceptance:
    """App-level narrowing of ``OrchestratorCapabilities.input_attachment_types`` by
    ``LazyOnDemandAttachmentStrategy.accepted_types``, when configured.

    The deployment's declared types remain a hard cap; ``accepted_types`` can only
    narrow them, never widen — a mime must match both lists.
    """

    def __init__(
        self,
        capabilities: OrchestratorCapabilities,
        *,
        accepted_types: list[str] | None = None,
    ) -> None:
        self._capabilities: OrchestratorCapabilities = capabilities
        self._accepted_types: list[str] | None = accepted_types

    @property
    def deployment_id(self) -> str:
        return self._capabilities.deployment_id

    @property
    def advertised_input_attachment_types(self) -> list[str] | None:
        """The allowlist to advertise to the model: ``accepted_types`` verbatim when
        set — it is the narrower intent by construction — otherwise the deployment's
        declared ``input_attachment_types``."""
        if self._accepted_types is not None:
            return self._accepted_types
        return self._capabilities.input_attachment_types

    def accepts_mime_type(self, mime_type: str | None) -> bool:
        """Whether ``mime_type`` is accepted: it must match the deployment's
        ``input_attachment_types`` (hard cap) and, when configured, ``accepted_types``
        (app-level narrowing) — a conjunction, not an intersected pattern set."""
        if not matches_type(mime_type, self._capabilities.input_attachment_types):
            return False
        if self._accepted_types is not None and not matches_type(mime_type, self._accepted_types):
            return False
        return True
