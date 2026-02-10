"""Tests that verify the pre-transformer pipeline ordering.

The pipeline runs transformers sequentially:

    ReduceAttachmentTransformer -> AddContextAttachmentTransformer -> AttachmentNotificationInjector

- ReduceAttachmentTransformer handles user attachments by injecting text metadata
  into user message content and keeping only image attachments inline.
- AddContextAttachmentTransformer adds context files to custom_content after reduction,
  so they are never treated as user-uploaded attachments.
- AttachmentNotificationInjector handles admin-configured context files by injecting
  synthetic tool call/result messages.
"""

import json

from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role
from pydantic.v1 import StrictStr

from quickapp.attachment_processing._attachment_notification_injector import _AttachmentNotificationInjector
from quickapp.attachment_processing._message_transformers import _AddContextAttachmentTransformer, \
    _ReduceAttachmentTransformer
from quickapp.attachment_processing._tool_configs import AVAILABLE_CONTEXT_TOOL_NAME
from quickapp.config.context import FileContextConfig



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


def _run_pipeline(
    messages: list[Message], contexts: list[FileContextConfig] | None = None
) -> list[Message]:
    """Run transformers in the production pipeline order."""
    ctx_list = contexts or []
    context_adder = _AddContextAttachmentTransformer(ctx_list)
    reducer = _ReduceAttachmentTransformer()
    injector = _AttachmentNotificationInjector(
        contexts=ctx_list,
    )

    messages = reducer.transform(messages)
    messages = context_adder.transform(messages)
    messages = injector.transform(messages)
    return messages


class TestUserAttachmentsPipeline:
    def test_pdf_attachment_text_metadata_injected(self):
        messages = [
            _user_msg(
                "analyze this",
                [_attachment("report.pdf", "/files/report.pdf", "application/pdf")],
            )
        ]

        result = _run_pipeline(messages)

        assert len(result) == 1
        content = str(result[0].content)
        assert "Attachment report.pdf" in content
        assert "application/pdf" in content
        assert len(result[0].custom_content.attachments) == 0

    def test_image_attachment_kept_inline_with_text_metadata(self):
        messages = [
            _user_msg(
                "look",
                [_attachment("photo.png", "/files/photo.png", "image/png")],
            )
        ]

        result = _run_pipeline(messages)

        assert len(result) == 1
        assert len(result[0].custom_content.attachments) == 1
        content = str(result[0].content)
        assert "Attachment photo.png" in content


class TestContextPipeline:
    def test_context_file_notified_via_synthetic_tool_call(self):
        ctx = FileContextConfig(url="files/bucket/reference.pdf", description="Reference doc")
        messages = [_user_msg("hello")]

        result = _run_pipeline(messages, contexts=[ctx])

        # Original + synthetic assistant tool_call + tool result
        assert len(result) == 3
        assert result[1].role == Role.ASSISTANT
        assert result[1].tool_calls[0].function.name == AVAILABLE_CONTEXT_TOOL_NAME

        data = json.loads(result[2].content)
        assert len(data["entries"]) == 1
        assert data["entries"][0]["title"] == "reference.pdf"
        assert data["entries"][0]["url"] == "files/bucket/reference.pdf"
        assert data["entries"][0]["status"] == "new"


class TestCombinedPipeline:
    def test_user_attachment_text_and_context_tool_call(self):
        ctx = FileContextConfig(url="files/bucket/ref.csv")
        messages = [
            _user_msg(
                "check",
                [_attachment("doc.pdf", "/files/doc.pdf", "application/pdf")],
            )
        ]

        result = _run_pipeline(messages, contexts=[ctx])

        # Original message + 2 synthetic messages for context
        assert len(result) == 3

        # User message has text metadata for the PDF attachment
        content = str(result[0].content)
        assert "Attachment doc.pdf" in content

        # Context notified via synthetic tool call
        assert result[1].tool_calls[0].function.name == AVAILABLE_CONTEXT_TOOL_NAME
        data = json.loads(result[2].content)
        assert data["entries"][0]["title"] == "ref.csv"
