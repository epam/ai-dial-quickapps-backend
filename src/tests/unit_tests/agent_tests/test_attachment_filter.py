from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role

from quickapp.agent._attachment_filter import _AttachmentFilter


def _user_msg(content: str = "", attachments: list[Attachment] | None = None) -> Message:
    msg = Message(role=Role.USER, content=content)
    if attachments:
        msg.custom_content = CustomContent(attachments=attachments)
    return msg


def _attachment(title: str, url: str, mime_type: str) -> Attachment:
    return Attachment(
        title=title,
        url=url,
        type=mime_type,
    )


class Test_AttachmentFilter:
    def test_image_attachments_kept_inline(self):
        transformer = _AttachmentFilter()
        msg = _user_msg(
            "look at this",
            [_attachment("photo.png", "/files/photo.png", "image/png")],
        )
        result = transformer.filter_attachments([msg])
        assert len(result[0].custom_content.attachments) == 1
        assert result[0].custom_content.attachments[0].type == "image/png"

    def test_non_image_attachments_removed(self):
        transformer = _AttachmentFilter()
        msg = _user_msg(
            "check this",
            [_attachment("doc.pdf", "/files/doc.pdf", "application/pdf")],
        )
        result = transformer.filter_attachments([msg])
        assert len(result[0].custom_content.attachments) == 0

    def test_text_metadata_injected_for_attachments(self):
        transformer = _AttachmentFilter()
        msg = _user_msg(
            "original content",
            [
                _attachment("doc.pdf", "/files/doc.pdf", "application/pdf"),
                _attachment("photo.png", "/files/photo.png", "image/png"),
            ],
        )
        result = transformer.filter_attachments([msg])
        content = str(result[0].content)
        assert "Attachment doc.pdf" in content
        assert "application/pdf" in content

        # Image attachments are kept inline AND get text metadata injected
        assert "Attachment photo.png" in content
        assert "image/png" in content
        assert result[0].custom_content.attachments[0].type == "image/png"
        assert result[0].custom_content.attachments[0].title == "photo.png"

    def test_mixed_attachments_only_images_kept(self):
        transformer = _AttachmentFilter()
        msg = _user_msg(
            "",
            [
                _attachment("doc.pdf", "/files/doc.pdf", "application/pdf"),
                _attachment("photo.png", "/files/photo.png", "image/png"),
                _attachment("data.csv", "/files/data.csv", "text/csv"),
                _attachment("chart.jpg", "/files/chart.jpg", "image/jpeg"),
            ],
        )
        result = transformer.filter_attachments([msg])
        attachments = result[0].custom_content.attachments
        assert len(attachments) == 2
        types = {str(a.type) for a in attachments}
        assert types == {"image/png", "image/jpeg"}

    def test_filter_does_not_mutate_original_messages(self):
        transformer = _AttachmentFilter()
        msg = _user_msg(
            "hello",
            [_attachment("doc.pdf", "/files/doc.pdf", "application/pdf")],
        )
        original_content = str(msg.content)
        original_attachment_count = len(msg.custom_content.attachments)

        transformer.filter_attachments([msg])

        assert str(msg.content) == original_content
        assert len(msg.custom_content.attachments) == original_attachment_count

    def test_filter_idempotent_on_repeated_calls(self):
        """Calling filter_attachments twice on the same list produces identical output."""
        transformer = _AttachmentFilter()
        msg = _user_msg(
            "hello",
            [_attachment("doc.pdf", "/files/doc.pdf", "application/pdf")],
        )
        messages = [msg]

        first_pass = transformer.filter_attachments(messages)
        first_content = str(first_pass[0].content)

        second_pass = transformer.filter_attachments(messages)
        second_content = str(second_pass[0].content)

        assert first_content == second_content
        assert first_content.count("Attachment doc.pdf") == 1
