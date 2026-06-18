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
