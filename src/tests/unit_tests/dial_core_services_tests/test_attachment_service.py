import base64
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from quickapp.common.dial_settings import DialSettings
from quickapp.common.dial_core_client import Attachment
from quickapp.dial_core_services.attachment_service import AttachmentService


@pytest.mark.asyncio
async def test_upload_attachment_success_with_title():
    dial_settings = DialSettings(url="http://dial-core", api_version="2025-01-01-preview")
    api_key = SecretStr("apikey")

    raw = b"hello world"
    encoded = base64.b64encode(raw).decode()
    attachment = Attachment(title="myfile.txt", url=None, data=encoded, type="text/plain")

    mock_ctx = AsyncMock()
    mock_client = AsyncMock()
    mock_client.put_file.return_value = {"url": "https://example.com/myfile.txt"}
    mock_ctx.__aenter__.return_value = mock_client
    mock_ctx.__aexit__.return_value = None

    with patch("quickapp.dial_core_services.attachment_service.DialCoreClient", return_value=mock_ctx) as mock_dc:
        svc = AttachmentService(dial_settings, api_key)
        result = await svc.upload_attachment_to_core(attachment)

    mock_dc.assert_called_once_with(base_url=dial_settings.url, api_key=api_key)
    mock_client.put_file.assert_awaited_once()
    called_kwargs = mock_client.put_file.await_args.kwargs
    assert called_kwargs["name"] == "myfile.txt"
    assert called_kwargs["mime_type"] == "text/plain"
    assert isinstance(called_kwargs["content"], BytesIO)
    assert result.data is None
    assert result.url == "https://example.com/myfile.txt"


@pytest.mark.asyncio
async def test_upload_attachment_generates_name_when_no_title():
    dial_settings = DialSettings(url="https://dial-core", api_version="2025-01-01-preview")
    api_key = SecretStr("apikey")

    raw = b"data"
    encoded = base64.b64encode(raw).decode()
    attachment = Attachment(title=None, url=None, data=encoded, type="application/octet-stream")

    mock_ctx = AsyncMock()
    mock_client = AsyncMock()
    mock_client.put_file.return_value = {"url": "https://example.com/generated.bin"}
    mock_ctx.__aenter__.return_value = mock_client
    mock_ctx.__aexit__.return_value = None

    with patch("quickapp.dial_core_services.attachment_service.DialCoreClient", return_value=mock_ctx):
        with patch("quickapp.dial_core_services.attachment_service.generate_attachment_filename", return_value="generated.bin"):
            svc = AttachmentService(dial_settings, api_key)
            result = await svc.upload_attachment_to_core(attachment)

    mock_client.put_file.assert_awaited_once()
    called_kwargs = mock_client.put_file.await_args.kwargs
    assert called_kwargs["name"] == "generated.bin"
    assert result.url == "https://example.com/generated.bin"
    assert result.data is None


@pytest.mark.asyncio
async def test_upload_attachment_on_exception_keeps_data():
    dial_settings = DialSettings(url="https://dial-core", api_version="2025-01-01-preview")
    api_key = SecretStr("apikey")

    attachment = Attachment(title="fail.txt", url=None, data="rawdata", type="text/plain")

    mock_ctx = AsyncMock()
    mock_client = AsyncMock()
    mock_client.put_file.side_effect = Exception("upload failed as expected in test case, just ignore this message")
    mock_ctx.__aenter__.return_value = mock_client
    mock_ctx.__aexit__.return_value = None

    with patch("quickapp.dial_core_services.attachment_service.DialCoreClient", return_value=mock_ctx):
        svc = AttachmentService(dial_settings, api_key)
        # noinspection PyBroadException
        try:
            result = await svc.upload_attachment_to_core(attachment)
        except Exception:
            pass # Suppress exception for test
    assert result.data == "rawdata"
    assert result.url is None