"""A stand-in for ``ProjectFilesClient.stream`` in unit tests."""

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
from aidial_client.types.file import FileDownloadResponse


class _ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: Iterable[bytes]):
        self._chunks = list(chunks)
        self.read_chunks = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.read_chunks += 1
            yield chunk


def streamed_response(
    chunks: Iterable[bytes],
    *,
    content_length: int | None = None,
    etag: str | None = "file-etag",
    content_type: str | None = "text/markdown",
) -> tuple[FileDownloadResponse, _ChunkStream]:
    """A streamed response whose body hasn't been read; the stream counts the chunks read."""
    headers = {
        name: value
        for name, value in {
            "content-length": None if content_length is None else str(content_length),
            "etag": etag,
            "content-type": content_type,
        }.items()
        if value is not None
    }
    stream = _ChunkStream(chunks)
    response = httpx.Response(200, headers=headers, stream=stream)
    return FileDownloadResponse(response=response, filename="file"), stream


def project_stream(data: bytes, **headers) -> MagicMock:
    """``MagicMock`` for ``ProjectFilesClient.stream`` serving ``data`` with Content-Length."""

    @asynccontextmanager
    async def _stream(_url: str) -> AsyncIterator[FileDownloadResponse]:
        response, _ = streamed_response([data], content_length=len(data), **headers)
        yield response

    return MagicMock(side_effect=_stream)
