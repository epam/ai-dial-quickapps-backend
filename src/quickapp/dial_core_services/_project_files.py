"""Minimal client for the DIAL Core v2 project API.

A project file is addressed ``projects/{bucket}/{path}/files/{file}``. The v1 files API can't
reach it and aidial-client has no v2 project resource yet, so this goes through AsyncDial's
HTTP client (same base URL, auth, timeouts, retries and 404/412 → typed exceptions). Replace it
with aidial-client's project API once that exists.

Core behaviour this relies on:

- ``If-Match`` / ``If-None-Match`` on a file PUT are checked against the *project* ETag,
  while a file GET returns the file's own ETag. So callers check a file's own state with
  ``file_etag`` and then send a plain PUT.
- There is no per-file metadata endpoint, and listings carry no sizes.
- Listing a missing folder returns 200 with no items, never 404.
"""

from http import HTTPStatus
from typing import Literal

import httpx
from aidial_client import AsyncDial
from aidial_client._exception import DialException, ResourceNotFoundError
from aidial_client._http_client._base import ErrorHandler
from aidial_client._internal_types._http_request import FinalRequestOptions
from aidial_client.helpers.storage_resource import (
    _percent_encode_relative_url,
    _storage_error_processor,
)
from aidial_client.types.metadata import FileMetadata
from injector import inject
from pydantic import BaseModel, ConfigDict

from quickapp.common.project_context import has_unsafe_segments


class _RangeNotSatisfiableError(DialException):
    """A 416 on a one-byte ranged GET: the file exists but is empty."""

    def __init__(self, etag: str | None):
        super().__init__(
            message="Range not satisfiable", status_code=HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE
        )
        self.etag = etag


def _ranged_get_error_processor(
    http_status_error: httpx.HTTPStatusError,
) -> DialException | None:
    response = http_status_error.response
    if response.status_code == HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE:
        return _RangeNotSatisfiableError(response.headers.get("etag"))
    return _storage_error_processor(http_status_error)


class ProjectItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    is_folder: bool


@inject
class ProjectFilesClient:
    def __init__(self, dial_client: AsyncDial) -> None:
        self._http = dial_client.deployments.http_client

    async def download(self, url: str) -> tuple[bytes, FileMetadata]:
        """Download a project file with a synthesized ``FileMetadata``.

        ``etag`` is the file's own ETag, not the project's (see the module doc). No size
        limit here: callers check it after the download.
        """
        response = await self._request("GET", f"v2/{url}")
        data = response.content
        metadata = FileMetadata(
            name=url.rsplit("/", 1)[-1],
            bucket=url.split("/")[1],
            url=url,
            node_type="ITEM",
            resource_type="FILE",
            content_length=len(data),
            content_type=response.headers.get("content-type"),
            etag=response.headers.get("etag"),
        )
        return data, metadata

    async def file_etag(self, url: str) -> str | None:
        """The file's own ETag, or ``None`` when the file doesn't exist.

        Asks for the first byte only (200 or 206 both work); if Core ignores ``Range`` the
        whole file comes back, which is slower but still correct. A 0-byte file answers
        416 (no byte 0): it exists, and the ETag comes from that response.
        """
        try:
            response = await self._request(
                "GET",
                f"v2/{url}",
                headers={"Range": "bytes=0-0"},
                on_http_error=_ranged_get_error_processor,
            )
        except ResourceNotFoundError:
            return None
        except _RangeNotSatisfiableError as e:
            return e.etag
        return response.headers.get("etag")

    async def put(self, url: str, content: bytes, content_type: str) -> None:
        """Upload a file unconditionally (create or replace)."""
        filename = url.rsplit("/", 1)[-1]
        await self._request("PUT", f"v2/{url}", files={"file": (filename, content, content_type)})

    async def delete(self, url: str) -> None:
        await self._request("DELETE", f"v2/{url}")

    async def list(self, folder_url: str) -> list[ProjectItem]:
        """Direct children of a project folder (all pages)."""
        items: list[ProjectItem] = []
        token: str | None = None
        while True:
            response = await self._request(
                "GET",
                f"v2/metadata/{folder_url.rstrip('/')}",
                params={"token": token} if token else None,
            )
            body = response.json()
            for item in body.get("items") or []:
                is_folder = item.get("nodeType") == "FOLDER"
                item_url: str = item["url"]
                if is_folder and not item_url.endswith("/"):
                    item_url += "/"
                items.append(ProjectItem(url=item_url, is_folder=is_folder))
            token = body.get("nextToken")
            if not token:
                return items

    async def _request(
        self,
        method: Literal["GET", "PUT", "DELETE"],
        url: str,
        *,
        files: dict | None = None,
        params: dict | None = None,
        headers: dict[str, str] | None = None,
        on_http_error: ErrorHandler = _storage_error_processor,
    ) -> httpx.Response:
        # Defence in depth: callers only pass URLs of the request's project, which are
        # checked already; never send a path that could leave it.
        if has_unsafe_segments(url):
            raise DialException(message=f"Invalid project resource path: {url}", status_code=400)
        options = FinalRequestOptions(
            method=method,
            url=_percent_encode_relative_url(url),
            files=files,
            params=params,
            headers=headers or {},
        )
        return await self._http.request(
            cast_to=httpx.Response, options=options, on_http_error=on_http_error
        )
