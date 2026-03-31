from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quickapp.common.media_types import MediaTypes
from quickapp.internal_tooling.py_interpreter_tooling.handlers.display_content_processor import (
    DisplayContentProcessor,
)
from quickapp.internal_tooling.py_interpreter_tooling.model.response import CodeExecutionResponse


def _make_processor() -> DisplayContentProcessor:
    dial_settings = MagicMock()
    dial_settings.url = "http://test"
    api_key = MagicMock()
    return DisplayContentProcessor(dial_settings=dial_settings, api_key=api_key)


def _mock_put_file(url: str = "http://test/bucket/file.png"):
    mock_client = AsyncMock()
    mock_client.put_file = AsyncMock(return_value={"url": url})
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return patch(
        "quickapp.internal_tooling.py_interpreter_tooling.handlers.display_content_processor.DialCoreClient",
        return_value=mock_client,
    )


@pytest.mark.asyncio
async def test_single_attachment_with_display_title():
    processor = _make_processor()
    display = [{MediaTypes.PNG: "dGVzdA=="}]

    with _mock_put_file("http://test/bucket/chart.png"):
        result = await processor.process_display_content(display, display_title="Sales Chart")

    assert len(result) == 1
    assert result[0].title == "Sales Chart"
    assert result[0].url == "http://test/bucket/chart.png"
    assert result[0].type == MediaTypes.PNG


@pytest.mark.asyncio
async def test_multiple_attachments_with_display_title():
    processor = _make_processor()
    display = [
        {MediaTypes.PNG: "dGVzdA==", MediaTypes.PLOTLY: {"data": [], "layout": {}}},
    ]

    with _mock_put_file("http://test/bucket/file"):
        result = await processor.process_display_content(display, display_title="My Chart")

    assert len(result) == 2
    assert result[0].title == "My Chart (1)"
    assert result[1].title == "My Chart (2)"


@pytest.mark.asyncio
async def test_no_display_title():
    processor = _make_processor()
    display = [{MediaTypes.PNG: "dGVzdA=="}]

    with _mock_put_file("http://test/bucket/file.png"):
        result = await processor.process_display_content(display)

    assert len(result) == 1
    assert result[0].title is None


@pytest.mark.asyncio
async def test_multiple_display_items_with_title():
    processor = _make_processor()
    display = [
        {MediaTypes.PNG: "dGVzdA=="},
        {MediaTypes.JPEG: "dGVzdA=="},
    ]

    with _mock_put_file("http://test/bucket/file"):
        result = await processor.process_display_content(display, display_title="Results")

    assert len(result) == 2
    assert result[0].title == "Results (1)"
    assert result[1].title == "Results (2)"


@pytest.mark.asyncio
async def test_empty_display_content():
    processor = _make_processor()

    with _mock_put_file():
        result = await processor.process_display_content([], display_title="Title")

    assert result == []


@pytest.mark.asyncio
async def test_unsupported_media_type_skipped():
    processor = _make_processor()
    display = [{"text/html": "<h1>hi</h1>"}]

    with _mock_put_file():
        result = await processor.process_display_content(display, display_title="Title")

    assert result == []


@pytest.mark.asyncio
async def test_sanitize_display_content():
    processor = _make_processor()
    response = CodeExecutionResponse(
        status="SUCCESS",
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
