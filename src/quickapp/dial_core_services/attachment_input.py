from typing import Any

from aidial_client.types.chat.request_param import AttachmentParam
from pydantic import BaseModel, ConfigDict, Field


class AttachmentInput(BaseModel):
    """Typed attachment payload accepted by deployment tools."""

    model_config = ConfigDict(extra="forbid")

    type: str | None = Field(default=None, description="MIME type of the attachment.")
    title: str | None = Field(default=None, description="Attachment title.")
    url: str | None = Field(default=None, description="Attachment URL when available.")
    data: str | None = Field(default=None, description="Inline attachment content as string.")

    def to_attachment_param(self) -> AttachmentParam:
        attachment = AttachmentParam(type=self.type or "")
        if self.title is not None:
            attachment["title"] = self.title
        if self.url is not None:
            attachment["url"] = self.url
        if self.data is not None:
            attachment["data"] = self.data
        return attachment

    @classmethod
    def parse_list(cls, values: list[Any] | None) -> list["AttachmentInput"]:
        if values is None:
            return []
        if not isinstance(values, list):
            raise TypeError("attachments must be a list")
        return [cls.model_validate(value) for value in values or []]


