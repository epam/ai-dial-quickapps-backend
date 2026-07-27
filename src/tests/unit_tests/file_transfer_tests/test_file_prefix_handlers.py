import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.file_transfer._file_loader_service import FileLoaderService
from quickapp.file_transfer._file_prefix_handlers import FilePrefixHandlers


@pytest.fixture
def mock_file_service() -> MagicMock:
    service = MagicMock(spec=FileLoaderService)
    service.load = AsyncMock()
    service.load_with_content_type = AsyncMock()
    return service


# ---------------------------------------------------------------------------
# handle_base64 tests
# ---------------------------------------------------------------------------


class TestHandleBase64:
    @pytest.mark.asyncio
    async def test_normal_bytes(self, mock_file_service):
        raw = b"hello world"
        mock_file_service.load.return_value = raw
        result = await FilePrefixHandlers.handle_base64(
            "files/test.bin", mock_file_service, parameter_name="input"
        )
        assert result == base64.b64encode(raw).decode()

    @pytest.mark.asyncio
    async def test_non_bytes_raises_exception_with_parameter_name(self, mock_file_service):
        mock_file_service.load.return_value = object()
        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await FilePrefixHandlers.handle_base64(
                "files/test.bin", mock_file_service, parameter_name="input"
            )
        assert excinfo.value.parameter_name == "input"

    @pytest.mark.asyncio
    async def test_parameter_name_threaded_to_file_service(self, mock_file_service):
        mock_file_service.load.return_value = b"data"
        await FilePrefixHandlers.handle_base64(
            "files/test.bin", mock_file_service, parameter_name="input"
        )
        mock_file_service.load.assert_awaited_once_with("files/test.bin", parameter_name="input")


# ---------------------------------------------------------------------------
# handle_data tests
# ---------------------------------------------------------------------------


class TestHandleData:
    @pytest.mark.asyncio
    async def test_wraps_as_rfc2397_data_uri(self, mock_file_service):
        raw = b"%PDF-1.4 content"
        mock_file_service.load_with_content_type.return_value = (raw, "application/pdf")
        result = await FilePrefixHandlers.handle_data(
            "files/doc.pdf", mock_file_service, parameter_name="uri"
        )
        assert result == f"data:application/pdf;base64,{base64.b64encode(raw).decode()}"

    @pytest.mark.asyncio
    async def test_parameter_name_threaded_to_file_service(self, mock_file_service):
        mock_file_service.load_with_content_type.return_value = (b"x", "text/plain")
        await FilePrefixHandlers.handle_data(
            "files/test.txt", mock_file_service, parameter_name="uri"
        )
        mock_file_service.load_with_content_type.assert_awaited_once_with(
            "files/test.txt", parameter_name="uri"
        )

    @pytest.mark.asyncio
    async def test_non_bytes_raises_exception_with_parameter_name(self, mock_file_service):
        mock_file_service.load_with_content_type.return_value = (
            object(),
            "application/octet-stream",
        )
        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await FilePrefixHandlers.handle_data(
                "files/test.bin", mock_file_service, parameter_name="uri"
            )
        assert excinfo.value.parameter_name == "uri"


# ---------------------------------------------------------------------------
# handle_text tests
# ---------------------------------------------------------------------------


class TestHandleText:
    @pytest.mark.asyncio
    async def test_valid_utf8_text(self, mock_file_service):
        mock_file_service.load.return_value = "hello world".encode("utf-8")
        result = await FilePrefixHandlers.handle_text(
            "files/test.txt", mock_file_service, parameter_name="input"
        )
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_utf8_with_bom(self, mock_file_service):
        content = b"\xef\xbb\xbfhello with BOM"
        mock_file_service.load.return_value = content
        result = await FilePrefixHandlers.handle_text(
            "files/test.txt", mock_file_service, parameter_name="input"
        )
        assert result == "hello with BOM"

    @pytest.mark.asyncio
    async def test_non_utf8_decoded_with_replacement(self, mock_file_service):
        # Create bytes that are invalid UTF-8
        content = b"\x80\x81\x82"
        mock_file_service.load.return_value = content
        result = await FilePrefixHandlers.handle_text(
            "files/test.txt", mock_file_service, parameter_name="input"
        )
        assert "\ufffd" in result  # replacement character

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "signature,desc",
        [
            (b"\x89PNG\r\n\x1a\n", "PNG image"),
            (b"\xff\xd8\xff", "JPEG image"),
            (b"GIF8", "GIF image"),
            (b"%PDF-", "PDF document"),
            (b"PK\x03\x04", "ZIP archive"),
        ],
    )
    async def test_binary_signature_raises_exception(self, mock_file_service, signature, desc):
        mock_file_service.load.return_value = signature + b"\x00" * 100
        with pytest.raises(InvalidToolCallParameterException, match="binary"):
            await FilePrefixHandlers.handle_text(
                "files/test.bin", mock_file_service, parameter_name="input"
            )
