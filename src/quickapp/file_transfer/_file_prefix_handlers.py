import base64
import logging

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.file_transfer._file_loader_service import FileLoaderService

logger = logging.getLogger(__name__)

_BINARY_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "PNG image"),
    (b"\xff\xd8\xff", "JPEG image"),
    (b"GIF8", "GIF image"),
    (b"%PDF-", "PDF document"),
    (b"PK\x03\x04", "ZIP archive"),
]


class FilePrefixHandlers:
    """Static handlers for file:{prefix}::{file_url} processing."""

    @staticmethod
    async def handle_base64(
        file_url: str, file_service: FileLoaderService, parameter_name: str = "<unknown>"
    ) -> str:
        content = await file_service.load(file_url, parameter_name=parameter_name)
        if not isinstance(content, (bytes, bytearray)):
            try:
                content = bytes(content)
            except Exception:
                logger.exception("Failed to coerce downloaded content to bytes for %s", file_url)
                raise InvalidToolCallParameterException(
                    parameter_name=parameter_name,
                    message="Downloaded content is not bytes and cannot be converted to base64.",
                )
        return base64.b64encode(content).decode()

    @staticmethod
    async def handle_data(
        file_url: str, file_service: FileLoaderService, parameter_name: str = "<unknown>"
    ) -> str:
        content, mime_type = await file_service.load_with_content_type(
            file_url, parameter_name=parameter_name
        )
        if not isinstance(content, (bytes, bytearray)):
            try:
                content = bytes(content)
            except Exception:
                logger.exception(
                    "Failed to coerce downloaded content to bytes for %s",
                    file_url,
                )
                raise InvalidToolCallParameterException(
                    parameter_name=parameter_name,
                    message=(
                        "Downloaded content is not bytes and cannot be converted " "to a data URI."
                    ),
                )
        encoded = base64.b64encode(content).decode()
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    async def handle_text(
        file_url: str, file_service: FileLoaderService, parameter_name: str = "<unknown>"
    ) -> str:
        content_bytes = await file_service.load(file_url, parameter_name=parameter_name)

        if not isinstance(content_bytes, (bytes, bytearray)):
            try:
                content_bytes = bytes(content_bytes)
            except Exception:
                logger.exception("Failed to coerce downloaded content to bytes for %s", file_url)
                raise InvalidToolCallParameterException(
                    parameter_name=parameter_name,
                    message="Downloaded content is not bytes and cannot be converted to text.",
                )

        for sig, desc in _BINARY_SIGNATURES:
            if content_bytes.startswith(sig):
                logger.warning(
                    "Downloaded file %s appears to be binary (%s); 'text' prefix is invalid for binary files",
                    file_url,
                    desc,
                )
                raise InvalidToolCallParameterException(
                    parameter_name=parameter_name,
                    message=(
                        f"File at {file_url} appears to be binary ({desc}). "
                        "Use `file:data::...`, `file:base64::...` or `file:url::...` "
                        "instead of `file:text::...`."
                    ),
                )

        try:
            return content_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            return content_bytes.decode("utf-8", errors="replace")
