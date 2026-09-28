from typing import Literal

from pydantic import BaseModel, Field


class LazyOnDemandAttachmentStrategy(BaseModel):
    """Orchestrator receives admin/user files only on explicit
    ``internal_attachments_get_content`` tool calls (not as default-prompt
    attachments). MIME gating uses the orchestrator deployment's
    ``input_attachment_types`` from DialCore.
    """

    type: Literal["lazy_on_demand"] = Field(
        default="lazy_on_demand",
        description="Strategy discriminator.",
    )
    accepted_types: list[str] | None = Field(
        default=None,
        min_length=1,
        description=(
            "Narrows which MIME types the orchestrator will load for this app, within "
            "what the deployment's input_attachment_types allow. null (default) accepts "
            "everything the deployment declares. An empty list is rejected — omit the "
            "field (or use null) to mean 'no narrowing', since an empty list would mean "
            "'accept nothing'."
        ),
    )
