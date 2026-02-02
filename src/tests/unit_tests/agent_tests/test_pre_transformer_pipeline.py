"""Tests that verify the pre-transformer pipeline ordering.

The pipeline runs transformers sequentially, each receiving the output of the
previous one. The correct order is:

    AddContextAttachmentTransformer -> AttachmentNotificationInjector -> ReduceAttachmentTransformer

This ensures the injector captures metadata for ALL attachments (including PDFs,
CSVs, etc.) before the reducer strips non-image attachments from the messages
sent to the LLM.
"""

import json

import pytest
from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role
from pydantic.v1 import StrictStr

from quickapp.agent.processors.pre_transformers import (
    AttachmentNotificationInjector,
    ReduceAttachmentTransformer,
)
from quickapp.config.context import FileContextConfig
from quickapp.internal_tooling.attachment_notification_tooling._tool_configs import (
    AVAILABLE_ATTACHMENTS_TOOL_NAME,
    AVAILABLE_CONTEXT_TOOL_NAME,
)


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
    injector = AttachmentNotificationInjector(
        attachments_tool_name=AVAILABLE_ATTACHMENTS_TOOL_NAME,
        context_tool_name=AVAILABLE_CONTEXT_TOOL_NAME,
        contexts=contexts or [],
    )
    reducer = ReduceAttachmentTransformer()

    messages = injector.transform(messages)
    messages = reducer.transform(messages)
    return messages


class TestPipelineOrderCapturesAttachments:
    @pytest.mark.parametrize(
        "title, url, mime_type",
        [
            ("report.pdf", "/files/bucket/report.pdf", "application/pdf"),
            ("data.csv", "/files/bucket/data.csv", "text/csv"),
        ],
    )
    def test_non_image_attachment_captured_before_reduction(
        self, title: str, url: str, mime_type: str
    ):
        messages = [_user_msg("analyze this", [_attachment(title, url, mime_type)])]

        result = _run_pipeline(messages)

        # Original message + synthetic assistant tool_call + tool result
        assert len(result) == 3

        # Synthetic tool result contains the attachment metadata
        data = json.loads(result[2].content)
        assert len(data) == 1
        assert data[0]["title"] == title
        assert data[0]["url"] == url
        assert data[0]["type"] == mime_type
        assert data[0]["status"] == "new"

        # Reducer stripped the non-image attachment from user message
        assert len(result[0].custom_content.attachments) == 0

    def test_mixed_attachments_all_captured_only_images_kept(self):
        messages = [
            _user_msg(
                "review these files",
                [
                    _attachment("report.pdf", "/files/report.pdf", "application/pdf"),
                    _attachment("photo.png", "/files/photo.png", "image/png"),
                    _attachment("data.csv", "/files/data.csv", "text/csv"),
                ],
            )
        ]

        result = _run_pipeline(messages)

        assert len(result) == 3

        # All three attachments captured by injector
        data = json.loads(result[2].content)
        assert len(data) == 3
        titles = {entry["title"] for entry in data}
        assert titles == {"report.pdf", "photo.png", "data.csv"}

        # Only image attachment survives reduction
        remaining = result[0].custom_content.attachments
        assert len(remaining) == 1
        assert remaining[0].type == "image/png"

    def test_context_file_captured_before_reduction(self):
        ctx = FileContextConfig(url="files/bucket/reference.pdf", description="Reference doc")
        messages = [_user_msg("hello")]

        result = _run_pipeline(messages, contexts=[ctx])

        # Original + synthetic assistant tool_call + tool result
        assert len(result) == 3

        data = json.loads(result[2].content)
        assert len(data) == 1
        assert data[0]["title"] == "reference.pdf"
        assert data[0]["url"] == "files/bucket/reference.pdf"
        assert data[0]["status"] == "new"


class TestReversedOrderLosesNotification:
    """Demonstrates the bug when reducer runs before injector."""

    def test_attachment_not_captured_when_reducer_runs_first(self):
        injector = AttachmentNotificationInjector(
            attachments_tool_name=AVAILABLE_ATTACHMENTS_TOOL_NAME,
            context_tool_name=AVAILABLE_CONTEXT_TOOL_NAME,
            contexts=[],
        )
        reducer = ReduceAttachmentTransformer()

        messages = [
            _user_msg(
                "analyze this",
                [_attachment("report.pdf", "/files/bucket/report.pdf", "application/pdf")],
            )
        ]

        # Wrong order: reduce first, then inject
        messages = reducer.transform(messages)
        messages = injector.transform(messages)

        # Injector sees no attachments (reducer already removed the PDF),
        # so no synthetic messages are injected
        assert len(messages) == 1
        assert messages[0].role == Role.USER
