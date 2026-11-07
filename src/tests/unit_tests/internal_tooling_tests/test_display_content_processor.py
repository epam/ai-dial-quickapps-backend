from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quickapp.common.media_types import MediaTypes
from quickapp.common.project_context import ProjectContext
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.internal_tooling.py_interpreter_tooling.handlers.display_content_processor import (
    DisplayContentProcessor,
)
from quickapp.internal_tooling.py_interpreter_tooling.model.response import CodeExecutionResponse


def _make_dial_client(file_url: str) -> MagicMock:
    dial_client = MagicMock()

    bucket_resp = MagicMock()
    bucket_resp.appdata = "appdata_bucket"
    bucket_resp.bucket = "default_bucket"
    dial_client.bucket.get_raw = AsyncMock(return_value=bucket_resp)

    metadata = MagicMock()
    metadata.url = file_url
    dial_client.files.upload = AsyncMock(return_value=metadata)
    return dial_client


def _make_processor(
    file_url: str = "http://test/bucket/file.png",
    project: ProjectContext | None = None,
    file_service: MagicMock | None = None,
    dial_client: MagicMock | None = None,
) -> DisplayContentProcessor:
    attachment_service = AttachmentService(
        dial_client=dial_client or _make_dial_client(file_url),
        file_service=file_service or MagicMock(spec=DialFileService),
        project=project,
    )
    return DisplayContentProcessor(attachment_service=attachment_service)


@pytest.mark.asyncio
async def test_chart_without_project_goes_to_appdata_root():
    dial_client = _make_dial_client("files/appdata_bucket/chart.png")
    processor = _make_processor(dial_client=dial_client)

    with patch(
        "quickapp.internal_tooling.py_interpreter_tooling.handlers.display_content_processor"
        ".generate_attachment_filename",
        return_value="chart.png",
    ):
        result = await processor.process_display_content([{MediaTypes.PNG: "dGVzdA=="}])

    dial_client.files.upload.assert_awaited_once_with(
        url="files/appdata_bucket/chart.png", file=("chart.png", b"test", MediaTypes.PNG)
    )
    assert result[0].url == "files/appdata_bucket/chart.png"


@pytest.mark.asyncio
async def test_chart_in_project_goes_to_artifacts():
    file_service = MagicMock(spec=DialFileService)
    file_service.write_bytes = AsyncMock(side_effect=lambda url, *_, **__: url)
    processor = _make_processor(
        project=ProjectContext(url="projects/user-bucket/p"), file_service=file_service
    )

    with patch(
        "quickapp.internal_tooling.py_interpreter_tooling.handlers.display_content_processor"
        ".generate_attachment_filename",
        return_value="chart.png",
    ):
        result = await processor.process_display_content([{MediaTypes.PNG: "dGVzdA=="}])

    file_service.write_bytes.assert_awaited_once_with(
        "projects/user-bucket/p/files/artifacts/chart.png",
        b"test",
        content_type=MediaTypes.PNG,
        overwrite=True,
    )
    assert result[0].url == "projects/user-bucket/p/files/artifacts/chart.png"


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
    display = [
        {MediaTypes.PNG: "dGVzdA==", MediaTypes.PLOTLY: {"data": [], "layout": {}}},
    ]

    result = await processor.process_display_content(display, display_title="My Chart")

    assert len(result) == 2
    assert result[0].title == "My Chart (1)"
    assert result[1].title == "My Chart (2)"


@pytest.mark.asyncio
async def test_no_display_title():
    processor = _make_processor("http://test/bucket/file.png")
    display = [{MediaTypes.PNG: "dGVzdA=="}]

    result = await processor.process_display_content(display)

    assert len(result) == 1
    assert result[0].title is None


@pytest.mark.asyncio
async def test_multiple_display_items_with_title():
    processor = _make_processor("http://test/bucket/file")
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
    processor = _make_processor()

    result = await processor.process_display_content([], display_title="Title")

    assert result == []


@pytest.mark.asyncio
async def test_unsupported_media_type_skipped():
    processor = _make_processor()
    display = [{"text/html": "<h1>hi</h1>"}]

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
