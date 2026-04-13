from unittest.mock import AsyncMock

import pytest

from quickapp.common.media_types import MediaTypes
from quickapp.internal_tooling.py_interpreter_tooling.handlers.display_content_processor import (
    DisplayContentProcessor,
)
from quickapp.internal_tooling.py_interpreter_tooling.model.response import CodeExecutionResponse
from tests.unit_tests.common.common import mock_dial_core_client_factory


def _make_processor(url: str = "http://test/bucket/file.png") -> DisplayContentProcessor:
    mock_client = AsyncMock()
    mock_client.put_file.return_value = {"url": url}
    factory, _ = mock_dial_core_client_factory(mock_client)
    return DisplayContentProcessor(dial_core_client_factory=factory)


@pytest.mark.asyncio
async def test_single_attachment_with_display_title():
    processor = _make_processor("http://test/bucket/chart.png")
    display = [{MediaTypes.PNG: "dGVzdA=="}]

    result = await processor.process_display_content(display, display_title="Sales Chart")

    assert len(result) == 1
    assert result[0].title == "Sales Chart"
    assert result[0].url == "http://test/bucket/chart.png"
    assert result[0].type == MediaTypes.PNG


@pytest.mark.asyncio
async def test_multiple_attachments_with_display_title():
    processor = _make_processor("http://test/bucket/file")
    display = [{MediaTypes.PNG: "dGVzdA==", MediaTypes.PLOTLY: {"data": [], "layout": {}}}]

    result = await processor.process_display_content(display, display_title="My Chart")

    assert len(result) == 2
    assert result[0].title == "My Chart (1)"
    assert result[1].title == "My Chart (2)"


@pytest.mark.asyncio
async def test_no_display_title():
    processor = _make_processor()
    display = [{MediaTypes.PNG: "dGVzdA=="}]

    result = await processor.process_display_content(display)

    assert len(result) == 1
    assert result[0].title is None


@pytest.mark.asyncio
async def test_multiple_display_items_with_title():
    processor = _make_processor("http://test/bucket/file")
    display = [{MediaTypes.PNG: "dGVzdA=="}, {MediaTypes.JPEG: "dGVzdA=="}]

    result = await processor.process_display_content(display, display_title="Results")

    assert len(result) == 2
    assert result[0].title == "Results (1)"
    assert result[1].title == "Results (2)"


@pytest.mark.asyncio
async def test_empty_display_content():
    result = await _make_processor().process_display_content([], display_title="Title")
    assert result == []


@pytest.mark.asyncio
async def test_unsupported_media_type_skipped():
    display = [{"text/html": "<h1>hi</h1>"}]
    result = await _make_processor().process_display_content(display, display_title="Title")
    assert result == []


@pytest.mark.asyncio
async def test_sanitize_display_content():
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
    result = _make_processor().sanitize_display_content(response)

    assert result.display[0][MediaTypes.PLAIN_TEXT] == "some text"
    assert result.display[0][MediaTypes.PNG] == "Content will be presented as attachment"
    assert result.display[0][MediaTypes.PLOTLY] == "Content will be presented as attachment"
