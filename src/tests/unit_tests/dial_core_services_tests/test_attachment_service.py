import base64
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client.types.chat.response import Attachment

from quickapp.config.tools.base import AttachmentHandlingMode
from quickapp.dial_core_services.attachment_service import AttachmentService


def _make_mock_dial_client(
    bucket: str = "test-bucket", upload_url: str = "https://example.com/file"
) -> MagicMock:
    """Build a minimal AsyncDial mock covering bucket + files.upload."""
    bucket_resp = MagicMock()
    bucket_resp.appdata = None
    bucket_resp.bucket = bucket

    upload_result = MagicMock()
    upload_result.url = upload_url

    mock_client = MagicMock()
    mock_client.bucket.get_raw = AsyncMock(return_value=bucket_resp)
    mock_client.files.upload = AsyncMock(return_value=upload_result)
    return mock_client


@pytest.mark.asyncio
async def test_upload_attachment_success_with_title():
    mock_client = _make_mock_dial_client(upload_url="https://example.com/myfile.txt")
    attachment = Attachment(
        title="myfile.txt",
        url=None,
        data=base64.b64encode(b"hello world").decode(),
        type="text/plain",
    )

    svc = AttachmentService(dial_client=mock_client)
    result = await svc.upload_attachment_to_core(attachment)

    mock_client.bucket.get_raw.assert_awaited_once()
    mock_client.files.upload.assert_awaited_once()
    call_kwargs = mock_client.files.upload.call_args
    assert call_kwargs.kwargs["url"] == "files/test-bucket/myfile.txt"
    name, content, mime = call_kwargs.kwargs["file"]
    assert name == "myfile.txt"
    assert isinstance(content, bytes)
    assert mime == "text/plain"
    assert result.data is None
    assert result.url == "https://example.com/myfile.txt"


@pytest.mark.asyncio
async def test_upload_attachment_generates_name_when_no_title():
    mock_client = _make_mock_dial_client(upload_url="https://example.com/generated.bin")
    attachment = Attachment(
        title=None,
        url=None,
        data=base64.b64encode(b"data").decode(),
        type="application/octet-stream",
    )

    from unittest.mock import patch

    with patch(
        "quickapp.dial_core_services.attachment_service.generate_attachment_filename",
        return_value="generated.bin",
    ):
        svc = AttachmentService(dial_client=mock_client)
        result = await svc.upload_attachment_to_core(attachment)

    mock_client.files.upload.assert_awaited_once()
    call_kwargs = mock_client.files.upload.call_args
    assert call_kwargs.kwargs["url"] == "files/test-bucket/generated.bin"
    assert result.url == "https://example.com/generated.bin"
    assert result.data is None


@pytest.mark.asyncio
async def test_upload_attachment_on_exception_keeps_data():
    mock_client = _make_mock_dial_client()
    mock_client.bucket.get_raw.side_effect = Exception(
        "upload failed as expected in test case, just ignore this message"
    )
    attachment = Attachment(title="fail.txt", url=None, data="rawdata", type="text/plain")

    svc = AttachmentService(dial_client=mock_client)
    result = await svc.upload_attachment_to_core(attachment)

    assert result.data == "rawdata"
    assert result.url is None


@pytest.mark.asyncio
async def test_upload_skipped_when_url_already_set():
    mock_client = _make_mock_dial_client()
    attachment = Attachment(
        title="existing.txt", url="https://already-set.com/file", data=None, type="text/plain"
    )

    svc = AttachmentService(dial_client=mock_client)
    result = await svc.upload_attachment_to_core(attachment)

    mock_client.bucket.get_raw.assert_not_called()
    mock_client.files.upload.assert_not_called()
    assert result.url == "https://already-set.com/file"


@pytest.mark.asyncio
async def test_handle_attachment_inline_keeps_original_attachment():
    mock_client = _make_mock_dial_client()
    attachment = Attachment(title="inline.txt", url=None, data="inline-data", type="text/plain")

    svc = AttachmentService(dial_client=mock_client)
    result = await svc.handle_attachment(
        attachment,
        AttachmentHandlingMode.inline,
    )

    mock_client.bucket.get_raw.assert_not_called()
    mock_client.files.upload.assert_not_called()
    assert result.data == "inline-data"
    assert result.url is None


@pytest.mark.asyncio
async def test_handle_attachment_upload_to_core_uploads():
    mock_client = _make_mock_dial_client(upload_url="https://example.com/generated.txt")
    attachment = Attachment(title="generated.txt", url=None, data="hello", type="text/plain")

    svc = AttachmentService(dial_client=mock_client)
    result = await svc.handle_attachment(
        attachment,
        AttachmentHandlingMode.upload_to_core,
    )

    mock_client.bucket.get_raw.assert_awaited_once()
    mock_client.files.upload.assert_awaited_once()
    assert result.data is None
    assert result.url == "https://example.com/generated.txt"
