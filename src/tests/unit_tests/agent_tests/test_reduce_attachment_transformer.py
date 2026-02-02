from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role
from pydantic.v1 import StrictStr

from quickapp.agent.processors.pre_transformers import ReduceAttachmentTransformer


def _user_msg(content: str = "", attachments: list[Attachment] | None = None) -> Message:
    msg = Message(role=Role.USER, content=StrictStr(content))
    if attachments:
        msg.custom_content = CustomContent(attachments=attachments)
    return msg


def _attachment(title: str, url: str, mime_type: str) -> Attachment:
    return Attachment(
        title=StrictStr(title),
        url=StrictStr(url),
        type=StrictStr(mime_type),
    )


class TestReduceAttachmentTransformer:
    def test_image_attachments_kept_inline(self):
        transformer = ReduceAttachmentTransformer()
        msg = _user_msg(
            "look at this",
            [_attachment("photo.png", "/files/photo.png", "image/png")],
        )
        result = transformer.transform([msg])
        assert len(result[0].custom_content.attachments) == 1
        assert result[0].custom_content.attachments[0].type == "image/png"

    def test_non_image_attachments_removed(self):
        transformer = ReduceAttachmentTransformer()
        msg = _user_msg(
            "check this",
            [_attachment("doc.pdf", "/files/doc.pdf", "application/pdf")],
        )
        result = transformer.transform([msg])
        assert len(result[0].custom_content.attachments) == 0

    def test_text_metadata_injected_for_attachments(self):
        transformer = ReduceAttachmentTransformer()
        msg = _user_msg(
            "original content",
            [
                _attachment("doc.pdf", "/files/doc.pdf", "application/pdf"),
                _attachment("photo.png", "/files/photo.png", "image/png"),
            ],
        )
        result = transformer.transform([msg])
        content = str(result[0].content)
        assert "Attachment doc.pdf" in content
        assert "application/pdf" in content
        assert "Attachment photo.png" in content
        assert "image/png" in content

    def test_mixed_attachments_only_images_kept(self):
        transformer = ReduceAttachmentTransformer()
        msg = _user_msg(
            "",
            [
                _attachment("doc.pdf", "/files/doc.pdf", "application/pdf"),
                _attachment("photo.png", "/files/photo.png", "image/png"),
                _attachment("data.csv", "/files/data.csv", "text/csv"),
                _attachment("chart.jpg", "/files/chart.jpg", "image/jpeg"),
            ],
        )
        result = transformer.transform([msg])
        attachments = result[0].custom_content.attachments
        assert len(attachments) == 2
        types = {str(a.type) for a in attachments}
        assert types == {"image/png", "image/jpeg"}
