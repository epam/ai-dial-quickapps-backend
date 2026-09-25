from quickapp.common.utils import matches_type
from quickapp.config.tools.const import ALL_MIME_TYPES
from quickapp.core.agent import OrchestratorCapabilities


def _patterns_overlap(a: str, b: str) -> bool:
    """Whether MIME patterns ``a`` and ``b`` could ever both match the same concrete
    MIME type. Correct for the simple grammar used here (``*/*``, ``type/*``,
    ``type/subtype``): a wildcard overlaps another pattern whenever their top-level
    types agree; two exact patterns overlap only when they're identical."""
    if a == ALL_MIME_TYPES or b == ALL_MIME_TYPES:
        return True
    a_type = a.split("/", 1)[0]
    b_type = b.split("/", 1)[0]
    if a.endswith("/*") or b.endswith("/*"):
        return a_type == b_type
    return a == b


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
        """The allowlist to advertise to the model: ``accepted_types``, filtered down
        to entries that overlap the deployment's ``input_attachment_types`` in the
        first place, when set — otherwise the deployment's declared list verbatim.

        The filter is a cheap top-level-type overlap check (:func:`_patterns_overlap`),
        not full pattern intersection: e.g. ``accepted_types=["image/*"]`` against a
        deployment declaring concrete ``["image/png", "image/jpeg"]`` is kept verbatim
        even though the two lists don't textually intersect — the real gate
        (:meth:`accepts_mime_type`) still correctly accepts those concrete mimes. What
        the filter does catch is an ``accepted_types`` entry the deployment can never
        accept at all (e.g. ``application/*`` when the deployment only declares
        ``image/*``) — advertising that would promise the model a file type every
        real call would then reject.
        """
        if self._accepted_types is None:
            return self._capabilities.input_attachment_types
        deployment_types = self._capabilities.input_attachment_types
        if not deployment_types:
            return []
        return [
            accepted
            for accepted in self._accepted_types
            if any(_patterns_overlap(accepted, declared) for declared in deployment_types)
        ]

    def accepts_mime_type(self, mime_type: str | None) -> bool:
        """Whether ``mime_type`` is accepted: it must match the deployment's
        ``input_attachment_types`` (hard cap) and, when configured, ``accepted_types``
        (app-level narrowing) — a conjunction, not an intersected pattern set."""
        if not matches_type(mime_type, self._capabilities.input_attachment_types):
            return False
        if self._accepted_types is not None and not matches_type(mime_type, self._accepted_types):
            return False
        return True
