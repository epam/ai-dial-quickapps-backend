import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aidial_client.types.chat.response import Attachment

from quickapp.common.project_context import ProjectContext
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_core_services.dial_file_service import DialFileService

_PROJECT = ProjectContext(url="projects/user-bucket/My Project")
_ARTIFACTS = "projects/user-bucket/My%20Project/files/artifacts/"


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


def _make_file_service() -> MagicMock:
    file_service = MagicMock(spec=DialFileService)
    file_service.write_bytes = AsyncMock(side_effect=lambda url, *_, **__: url)
    return file_service


def _make_service(
    mock_client: MagicMock,
    project: ProjectContext | None = None,
    file_service: MagicMock | None = None,
) -> AttachmentService:
    return AttachmentService(
        dial_client=mock_client,
        file_service=file_service or _make_file_service(),
        project=project,
    )


def _attachment(title: str | None = "myfile.txt", data: bytes = b"hello world") -> Attachment:
    return Attachment(
        title=title, url=None, data=base64.b64encode(data).decode(), type="text/plain"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["upload_output_attachment", "upload_appdata_attachment"])
async def test_upload_attachment_without_project_goes_to_appdata_root(method: str):
    mock_client = _make_mock_dial_client(upload_url="https://example.com/myfile.txt")
    file_service = _make_file_service()
    svc = _make_service(mock_client, file_service=file_service)

    result = await getattr(svc, method)(_attachment())

    mock_client.bucket.get_raw.assert_awaited_once()
    mock_client.files.upload.assert_awaited_once()
    call_kwargs = mock_client.files.upload.call_args
    assert call_kwargs.kwargs["url"] == "files/test-bucket/myfile.txt"
    name, content, mime = call_kwargs.kwargs["file"]
    assert name == "myfile.txt"
    assert content == b"hello world"
    assert mime == "text/plain"
    assert result.data is None
    assert result.url == "https://example.com/myfile.txt"
    file_service.write_bytes.assert_not_awaited()


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
    mock_client.files.upload.assert_not_called()
    assert result.url == f"{_ARTIFACTS}myfile.txt"
    assert result.data is None


@pytest.mark.asyncio
async def test_upload_appdata_attachment_in_project_stays_in_appdata():
    mock_client = _make_mock_dial_client(upload_url="files/test-bucket/myfile.txt")
    file_service = _make_file_service()
    svc = _make_service(mock_client, project=_PROJECT, file_service=file_service)

    result = await svc.upload_appdata_attachment(_attachment())

    assert mock_client.files.upload.call_args.kwargs["url"] == "files/test-bucket/myfile.txt"
    file_service.write_bytes.assert_not_awaited()
    assert result.url == "files/test-bucket/myfile.txt"


@pytest.mark.asyncio
async def test_upload_attachment_generates_name_when_no_title():
    mock_client = _make_mock_dial_client(upload_url="https://example.com/generated.bin")
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
        svc = _make_service(mock_client)
        result = await svc.upload_output_attachment(attachment)

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

    svc = _make_service(mock_client)
    result = await svc.upload_output_attachment(attachment)

    assert result.data == "rawdata"
    assert result.url is None


@pytest.mark.asyncio
async def test_upload_output_attachment_in_project_on_exception_keeps_data():
    file_service = _make_file_service()
    file_service.write_bytes.side_effect = Exception(
        "upload failed as expected in test case, just ignore this message"
    )
    attachment = Attachment(title="fail.txt", url=None, data="rawdata", type="text/plain")

    svc = _make_service(_make_mock_dial_client(), project=_PROJECT, file_service=file_service)
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
    mock_client.files.upload.assert_not_called()
    file_service.write_bytes.assert_not_awaited()
    assert result.url == "https://already-set.com/file"


@pytest.mark.asyncio
async def test_upload_appdata_bytes_uploads_directly_and_returns_metadata():
    mock_client = _make_mock_dial_client(upload_url="https://example.com/raw.bin")
    svc = _make_service(mock_client, project=_PROJECT)

    metadata = await svc.upload_appdata_bytes(
        data=b"raw payload",
        content_type="application/octet-stream",
        filename="raw.bin",
    )

    mock_client.bucket.get_raw.assert_awaited_once()
    mock_client.files.upload.assert_awaited_once()
    call_kwargs = mock_client.files.upload.call_args.kwargs
    assert call_kwargs["url"] == "files/test-bucket/raw.bin"
    name, content, mime = call_kwargs["file"]
    assert name == "raw.bin"
    assert content == b"raw payload"
    assert mime == "application/octet-stream"
    assert metadata.url == "https://example.com/raw.bin"


@pytest.mark.asyncio
async def test_upload_appdata_bytes_propagates_failure():
    mock_client = _make_mock_dial_client()
    mock_client.files.upload.side_effect = RuntimeError("boom")
    svc = _make_service(mock_client)

    with pytest.raises(RuntimeError, match="boom"):
        await svc.upload_appdata_bytes(data=b"x", content_type="text/plain", filename="x.txt")


@pytest.mark.asyncio
async def test_upload_output_bytes_without_project_returns_appdata_url():
    mock_client = _make_mock_dial_client(upload_url="files/test-bucket/chart.png")
    svc = _make_service(mock_client)

    url = await svc.upload_output_bytes(data=b"png", content_type="image/png", filename="chart.png")

    assert mock_client.files.upload.call_args.kwargs["url"] == "files/test-bucket/chart.png"
    assert mock_client.files.upload.call_args.kwargs["file"] == ("chart.png", b"png", "image/png")
    assert url == "files/test-bucket/chart.png"


@pytest.mark.asyncio
async def test_upload_output_bytes_in_project_defaults_content_type():
    file_service = _make_file_service()
    svc = _make_service(_make_mock_dial_client(), project=_PROJECT, file_service=file_service)

    url = await svc.upload_output_bytes(data=b"x", content_type=None, filename="blob")

    file_service.write_bytes.assert_awaited_once_with(
        f"{_ARTIFACTS}blob", b"x", content_type="application/octet-stream", overwrite=True
    )
    assert url == f"{_ARTIFACTS}blob"


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["../PROJECT.md", "a/../../context/x.txt", "%2e%2e/x"])
async def test_upload_output_bytes_in_project_rejects_names_leaving_artifacts(filename: str):
    file_service = _make_file_service()
    svc = _make_service(_make_mock_dial_client(), project=_PROJECT, file_service=file_service)

    with pytest.raises(ValueError, match="Invalid output file name"):
        await svc.upload_output_bytes(data=b"x", content_type="text/plain", filename=filename)

    file_service.write_bytes.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_output_bytes_in_project_requires_the_artifacts_folder():
    # Defence in depth: a name that composes to a project URL outside artifacts/ is refused
    # even when it is a URL of the project.
    project = MagicMock(spec=ProjectContext)
    project.artifacts_root = _ARTIFACTS
    project.contains.return_value = True
    project.is_read_only.return_value = True
    file_service = _make_file_service()
    svc = _make_service(_make_mock_dial_client(), project=project, file_service=file_service)

    with pytest.raises(ValueError, match="Invalid output file name"):
        await svc.upload_output_bytes(data=b"x", content_type="text/plain", filename="x.txt")

    project.is_read_only.assert_called_once_with(f"{_ARTIFACTS}x.txt")
    file_service.write_bytes.assert_not_awaited()
