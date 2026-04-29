from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Attachment

from quickapp.common.media_types import MediaTypes
from quickapp.config.tools.base import AttachmentHandlingMode
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.internal_tooling.py_interpreter_tooling.handlers.display_content_processor import (
    DisplayContentProcessor,
)
from quickapp.internal_tooling.py_interpreter_tooling.model.response import (
    CodeExecutionResponse,
    ExecutionStatus,
)


def _make_processor(
    file_url: str = "http://test/bucket/file.png",
) -> tuple[DisplayContentProcessor, MagicMock]:
    attachment_service = MagicMock(spec=AttachmentService)

    def _prepare_attachment(
        attachment: Attachment,
        handling_mode: AttachmentHandlingMode,
    ) -> Attachment:
        if handling_mode == AttachmentHandlingMode.inline:
            return attachment
        attachment.url = file_url
        attachment.data = None
        return attachment

    attachment_service.handle_attachment = AsyncMock(side_effect=_prepare_attachment)

    return DisplayContentProcessor(attachment_service=attachment_service), attachment_service


@pytest.mark.asyncio
async def test_single_attachment_with_display_title():
    processor, _ = _make_processor("http://test/bucket/chart.png")
    display = [{MediaTypes.PNG: "dGVzdA=="}]

    result = await processor.process_display_content(display, display_title="Sales Chart")

    assert len(result) == 1
    assert result[0].title == "Sales Chart"
    assert result[0].url == "http://test/bucket/chart.png"
    assert result[0].type == MediaTypes.PNG


@pytest.mark.asyncio
async def test_multiple_attachments_with_display_title():
    processor, _ = _make_processor("http://test/bucket/file")
    display = [
        {MediaTypes.PNG: "dGVzdA==", MediaTypes.PLOTLY: {"data": [], "layout": {}}},
    ]

    result = await processor.process_display_content(display, display_title="My Chart")

    assert len(result) == 2
    assert result[0].title == "My Chart (1)"
    assert result[1].title == "My Chart (2)"


@pytest.mark.asyncio
async def test_no_display_title():
    processor, _ = _make_processor("http://test/bucket/file.png")
    display = [{MediaTypes.PNG: "dGVzdA=="}]

    result = await processor.process_display_content(display)

    assert len(result) == 1
    assert result[0].title is None


@pytest.mark.asyncio
async def test_multiple_display_items_with_title():
    processor, _ = _make_processor("http://test/bucket/file")
    display = [
        {MediaTypes.PNG: "dGVzdA=="},
        {MediaTypes.JPEG: "dGVzdA=="},
    ]

    result = await processor.process_display_content(display, display_title="Results")

    assert len(result) == 2
    assert result[0].title == "Results (1)"
    assert result[1].title == "Results (2)"


@pytest.mark.asyncio
async def test_empty_display_content():
    processor, _ = _make_processor()

    result = await processor.process_display_content([], display_title="Title")

    assert result == []


@pytest.mark.asyncio
async def test_unsupported_media_type_skipped():
    processor, attachment_service = _make_processor()
    display = [{"text/html": "<h1>hi</h1>"}]

    result = await processor.process_display_content(display, display_title="Title")

    assert result == []
    attachment_service.handle_attachment.assert_not_called()


@pytest.mark.asyncio
async def test_inline_handling_keeps_attachment_data():
    processor, attachment_service = _make_processor()
    display = [{MediaTypes.PLOTLY: {"data": [], "layout": {}}}]

    result = await processor.process_display_content(
        display,
        display_title="Plot",
        handling_mode=AttachmentHandlingMode.inline,
    )

    assert len(result) == 1
    assert result[0].title == "Plot"
    assert result[0].type == MediaTypes.PLOTLY
    assert result[0].url is None
    assert result[0].data == '{"data": [], "layout": {}}'
    attachment_service.handle_attachment.assert_awaited_once()


@pytest.mark.asyncio
async def test_sanitize_display_content():
    processor, _ = _make_processor()
    response = CodeExecutionResponse(
        status=ExecutionStatus.SUCCESS,
        display=[
            {
                MediaTypes.PLAIN_TEXT: "some text",
                MediaTypes.PNG: "dGVzdA==",
                MediaTypes.PLOTLY: {"data": []},
            }
        ],
    )

    result = processor.sanitize_display_content(response)

    assert result.display[0][MediaTypes.PLAIN_TEXT] == "some text"
    assert result.display[0][MediaTypes.PNG] == "Content will be presented as attachment"
    assert result.display[0][MediaTypes.PLOTLY] == "Content will be presented as attachment"
