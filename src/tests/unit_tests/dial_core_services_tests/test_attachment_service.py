import base64
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from aidial_client.types.chat.response import Attachment

from quickapp.dial_core_services.attachment_service import AttachmentService
from tests.unit_tests.common.common import mock_dial_core_client_factory


@pytest.mark.asyncio
async def test_upload_attachment_success_with_title():
    raw = b"hello world"
    encoded = base64.b64encode(raw).decode()
    attachment = Attachment(title="myfile.txt", url=None, data=encoded, type="text/plain")

    mock_client = AsyncMock()
    mock_client.put_file.return_value = {"url": "https://example.com/myfile.txt"}
    factory, _ = mock_dial_core_client_factory(mock_client)

    svc = AttachmentService(factory)
    result = await svc.upload_attachment_to_core(attachment)

    factory.create.assert_called_once_with()
    mock_client.put_file.assert_awaited_once()
    called_kwargs = mock_client.put_file.await_args.kwargs
    assert called_kwargs["name"] == "myfile.txt"
    assert called_kwargs["mime_type"] == "text/plain"
    assert isinstance(called_kwargs["content"], BytesIO)
    assert result.data is None
    assert result.url == "https://example.com/myfile.txt"


@pytest.mark.asyncio
async def test_upload_attachment_generates_name_when_no_title(monkeypatch):
    raw = b"data"
    encoded = base64.b64encode(raw).decode()
    attachment = Attachment(title=None, url=None, data=encoded, type="application/octet-stream")

    mock_client = AsyncMock()
    mock_client.put_file.return_value = {"url": "https://example.com/generated.bin"}
    factory, _ = mock_dial_core_client_factory(mock_client)

    monkeypatch.setattr(
        "quickapp.dial_core_services.attachment_service.generate_attachment_filename",
        lambda *a, **kw: "generated.bin",
    )

    svc = AttachmentService(factory)
    result = await svc.upload_attachment_to_core(attachment)

    mock_client.put_file.assert_awaited_once()
    called_kwargs = mock_client.put_file.await_args.kwargs
    assert called_kwargs["name"] == "generated.bin"
    assert result.url == "https://example.com/generated.bin"
    assert result.data is None


@pytest.mark.asyncio
async def test_upload_attachment_on_exception_keeps_data():
    attachment = Attachment(title="fail.txt", url=None, data="rawdata", type="text/plain")

    mock_client = AsyncMock()
    mock_client.put_file.side_effect = Exception(
        "upload failed as expected in test case, just ignore this message"
    )
    factory, _ = mock_dial_core_client_factory(mock_client)

    svc = AttachmentService(factory)
    try:
        result = await svc.upload_attachment_to_core(attachment)
    except Exception:
        pass  # Suppress exception for test
    assert result.data == "rawdata"
    assert result.url is None
