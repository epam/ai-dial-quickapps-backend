import base64
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aidial_client.types.chat.response import Attachment

from quickapp.common.project_context import ProjectContext
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_core_services.dial_file_service import DialFileService

_PROJECT = ProjectContext(url="projects/user-bucket/My Project")
_ARTIFACTS = "projects/user-bucket/My%20Project/files/artifacts/"
_APPDATA = "files/test-bucket/"

_UploadAttachment = Callable[[AttachmentService, Attachment], Awaitable[Attachment]]


def _make_mock_dial_client(bucket: str = "test-bucket") -> MagicMock:
    """Build a minimal AsyncDial mock covering the bucket call."""
    bucket_resp = MagicMock()
    bucket_resp.appdata = None
    bucket_resp.bucket = bucket

    mock_client = MagicMock()
    mock_client.bucket.get_raw = AsyncMock(return_value=bucket_resp)
    return mock_client


def _make_file_service() -> MagicMock:
    file_service = MagicMock(spec=DialFileService)
    file_service.write_bytes = AsyncMock(side_effect=lambda url, *_, **__: SimpleNamespace(url=url))
    return file_service


def _make_service(
    mock_client: MagicMock | None = None,
    project: ProjectContext | None = None,
    file_service: MagicMock | None = None,
) -> AttachmentService:
    return AttachmentService(
        dial_client=mock_client or _make_mock_dial_client(),
        file_service=file_service or _make_file_service(),
        project=project,
    )


def _attachment(title: str | None = "myfile.txt", data: bytes = b"hello world") -> Attachment:
    return Attachment(
        title=title, url=None, data=base64.b64encode(data).decode(), type="text/plain"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upload",
    [AttachmentService.upload_output_attachment, AttachmentService.upload_appdata_attachment],
)
async def test_upload_attachment_without_project_goes_to_appdata_root(upload: _UploadAttachment):
    mock_client = _make_mock_dial_client()
    file_service = _make_file_service()
    svc = _make_service(mock_client, file_service=file_service)

    result = await upload(svc, _attachment())

    mock_client.bucket.get_raw.assert_awaited_once()
    file_service.write_bytes.assert_awaited_once_with(
        f"{_APPDATA}myfile.txt", b"hello world", content_type="text/plain", overwrite=True
    )
    assert result.data is None
    assert result.url == f"{_APPDATA}myfile.txt"


@pytest.mark.asyncio
async def test_upload_output_attachment_in_project_goes_to_artifacts():
    mock_client = _make_mock_dial_client()
    file_service = _make_file_service()
    svc = _make_service(mock_client, project=_PROJECT, file_service=file_service)

    result = await svc.upload_output_attachment(_attachment())

    file_service.write_bytes.assert_awaited_once_with(
        f"{_ARTIFACTS}myfile.txt", b"hello world", content_type="text/plain", overwrite=True
    )
    mock_client.bucket.get_raw.assert_not_called()
    assert result.url == f"{_ARTIFACTS}myfile.txt"
    assert result.data is None


@pytest.mark.asyncio
async def test_upload_appdata_attachment_in_project_stays_in_appdata():
    file_service = _make_file_service()
    svc = _make_service(project=_PROJECT, file_service=file_service)

    result = await svc.upload_appdata_attachment(_attachment())

    assert file_service.write_bytes.await_args.args[0] == f"{_APPDATA}myfile.txt"
    assert result.url == f"{_APPDATA}myfile.txt"


@pytest.mark.asyncio
async def test_upload_attachment_generates_name_when_no_title():
    file_service = _make_file_service()
    attachment = Attachment(
        title=None,
        url=None,
        data=base64.b64encode(b"data").decode(),
        type="application/octet-stream",
    )

    with patch(
        "quickapp.dial_core_services.attachment_service.generate_attachment_filename",
        return_value="generated.bin",
    ):
        result = await _make_service(file_service=file_service).upload_output_attachment(attachment)

    assert file_service.write_bytes.await_args.args[0] == f"{_APPDATA}generated.bin"
    assert result.url == f"{_APPDATA}generated.bin"
    assert result.data is None


@pytest.mark.asyncio
async def test_upload_attachment_on_exception_keeps_data():
    mock_client = _make_mock_dial_client()
    mock_client.bucket.get_raw.side_effect = Exception(
        "upload failed as expected in test case, just ignore this message"
    )
    attachment = Attachment(title="fail.txt", url=None, data="rawdata", type="text/plain")

    result = await _make_service(mock_client).upload_output_attachment(attachment)

    assert result.data == "rawdata"
    assert result.url is None


@pytest.mark.asyncio
async def test_upload_output_attachment_in_project_on_exception_keeps_data():
    file_service = _make_file_service()
    file_service.write_bytes.side_effect = Exception(
        "upload failed as expected in test case, just ignore this message"
    )
    attachment = Attachment(title="fail.txt", url=None, data="rawdata", type="text/plain")

    svc = _make_service(project=_PROJECT, file_service=file_service)
    result = await svc.upload_output_attachment(attachment)

    assert result.data == "rawdata"
    assert result.url is None


@pytest.mark.asyncio
async def test_upload_skipped_when_url_already_set():
    mock_client = _make_mock_dial_client()
    file_service = _make_file_service()
    attachment = Attachment(
        title="existing.txt", url="https://already-set.com/file", data=None, type="text/plain"
    )

    svc = _make_service(mock_client, project=_PROJECT, file_service=file_service)
    result = await svc.upload_output_attachment(attachment)

    mock_client.bucket.get_raw.assert_not_called()
    file_service.write_bytes.assert_not_awaited()
    assert result.url == "https://already-set.com/file"


@pytest.mark.asyncio
async def test_upload_appdata_bytes_writes_under_the_appdata_root():
    file_service = _make_file_service()
    svc = _make_service(project=_PROJECT, file_service=file_service)

    uploaded = await svc.upload_appdata_bytes(
        data=b"raw payload", content_type="application/pdf", filename="raw.pdf"
    )

    file_service.write_bytes.assert_awaited_once_with(
        f"{_APPDATA}raw.pdf", b"raw payload", content_type="application/pdf", overwrite=True
    )
    assert uploaded.url == f"{_APPDATA}raw.pdf"


@pytest.mark.asyncio
async def test_appdata_bucket_is_asked_once_per_service():
    mock_client = _make_mock_dial_client()
    svc = _make_service(mock_client)

    await svc.upload_appdata_bytes(data=b"a", content_type="text/plain", filename="a.txt")
    await svc.upload_output_bytes(data=b"b", content_type="text/plain", filename="b.txt")

    mock_client.bucket.get_raw.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_appdata_bytes_propagates_failure():
    file_service = _make_file_service()
    file_service.write_bytes.side_effect = RuntimeError("boom")
    svc = _make_service(file_service=file_service)

    with pytest.raises(RuntimeError, match="boom"):
        await svc.upload_appdata_bytes(data=b"x", content_type="text/plain", filename="x.txt")


@pytest.mark.asyncio
async def test_upload_output_bytes_without_project_returns_appdata_url():
    file_service = _make_file_service()
    svc = _make_service(file_service=file_service)

    uploaded = await svc.upload_output_bytes(
        data=b"png", content_type="image/png", filename="chart.png"
    )

    file_service.write_bytes.assert_awaited_once_with(
        f"{_APPDATA}chart.png", b"png", content_type="image/png", overwrite=True
    )
    assert uploaded.url == f"{_APPDATA}chart.png"


@pytest.mark.asyncio
@pytest.mark.parametrize("project", [None, _PROJECT])
async def test_missing_content_type_defaults_to_binary(project: ProjectContext | None):
    file_service = _make_file_service()
    svc = _make_service(project=project, file_service=file_service)

    await svc.upload_output_bytes(data=b"x", content_type=None, filename="blob")

    assert file_service.write_bytes.await_args.kwargs["content_type"] == "application/octet-stream"


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["../PROJECT.md", "a/../../context/x.txt", "%2e%2e/x"])
async def test_upload_output_bytes_in_project_rejects_names_leaving_artifacts(filename: str):
    file_service = _make_file_service()
    svc = _make_service(project=_PROJECT, file_service=file_service)

    with pytest.raises(ValueError, match="Invalid output file name"):
        await svc.upload_output_bytes(data=b"x", content_type="text/plain", filename=filename)

    file_service.write_bytes.assert_not_awaited()
