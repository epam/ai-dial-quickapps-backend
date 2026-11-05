"""``ProjectFilesClient`` against a real AsyncDial; HTTP is intercepted by pytest-httpx."""

import pytest
from aidial_client import AsyncDial
from aidial_client._exception import DialException, EtagMismatchError, ResourceNotFoundError

from quickapp.dial_core_services._project_files import ProjectFilesClient

BASE_URL = "http://test-dial"
FILE_URL = "projects/b/My%20Project/files/artifacts/notes.md"


def _client() -> ProjectFilesClient:
    return ProjectFilesClient(AsyncDial(base_url=BASE_URL, api_key="key", max_retries=0))


@pytest.mark.asyncio
async def test_download_returns_bytes_and_the_files_own_etag(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/v2/{FILE_URL}",
        content=b"hello",
        headers={"etag": "file-etag", "content-type": "text/markdown"},
    )

    data, metadata = await _client().download(FILE_URL)

    assert data == b"hello"
    assert metadata.url == FILE_URL
    assert metadata.name == "notes.md"
    assert metadata.bucket == "b"
    assert metadata.etag == "file-etag"
    assert metadata.content_type == "text/markdown"
    assert metadata.content_length == 5


@pytest.mark.asyncio
async def test_file_etag_is_none_for_a_missing_file(httpx_mock) -> None:
    httpx_mock.add_response(method="GET", url=f"{BASE_URL}/v2/{FILE_URL}", status_code=404)

    assert await _client().file_etag(FILE_URL) is None


@pytest.mark.asyncio
async def test_download_of_a_missing_file_is_not_found(httpx_mock) -> None:
    httpx_mock.add_response(method="GET", url=f"{BASE_URL}/v2/{FILE_URL}", status_code=404)

    with pytest.raises(ResourceNotFoundError):
        await _client().download(FILE_URL)


@pytest.mark.asyncio
async def test_put_is_unconditional(httpx_mock) -> None:
    httpx_mock.add_response(method="PUT", url=f"{BASE_URL}/v2/{FILE_URL}", json={})

    await _client().put(FILE_URL, b"x", "text/plain")

    request = httpx_mock.get_requests()[0]
    assert "If-Match" not in request.headers
    assert "If-None-Match" not in request.headers
    assert b'filename="notes.md"' in request.content


@pytest.mark.asyncio
async def test_put_412_is_an_etag_mismatch(httpx_mock) -> None:
    httpx_mock.add_response(method="PUT", url=f"{BASE_URL}/v2/{FILE_URL}", status_code=412)

    with pytest.raises(EtagMismatchError):
        await _client().put(FILE_URL, b"x", "text/plain")


@pytest.mark.asyncio
async def test_403_keeps_its_status(httpx_mock) -> None:
    httpx_mock.add_response(method="DELETE", url=f"{BASE_URL}/v2/{FILE_URL}", status_code=403)

    with pytest.raises(DialException) as excinfo:
        await _client().delete(FILE_URL)
    assert not isinstance(excinfo.value, ResourceNotFoundError)
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_list_follows_pages_and_marks_folders(httpx_mock) -> None:
    folder = "projects/b/p/files/artifacts/"
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/v2/metadata/projects/b/p/files/artifacts",
        json={
            "items": [{"url": f"{folder}a.md", "nodeType": "ITEM"}],
            "nextToken": "t1",
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/v2/metadata/projects/b/p/files/artifacts?token=t1",
        json={"items": [{"url": f"{folder}sub", "nodeType": "FOLDER"}]},
    )

    items = await _client().list(folder)

    assert [(i.url, i.is_folder) for i in items] == [
        (f"{folder}a.md", False),
        (f"{folder}sub/", True),
    ]


@pytest.mark.parametrize("status", [200, 206])
@pytest.mark.asyncio
async def test_file_etag_asks_for_one_byte(httpx_mock, status) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/v2/{FILE_URL}",
        status_code=status,
        content=b"h",
        headers={"etag": "file-etag"},
    )

    assert await _client().file_etag(FILE_URL) == "file-etag"
    assert httpx_mock.get_requests()[0].headers["Range"] == "bytes=0-0"


@pytest.mark.parametrize(
    "url",
    [
        "projects/b/p/files/../../Other/files/x.md",
        "projects/b/p/files/%2e%2e/%2e%2e/Other/files/x.md",
        "projects/b/p/files//x.md",
    ],
)
@pytest.mark.asyncio
async def test_unsafe_paths_never_reach_core(httpx_mock, url) -> None:
    with pytest.raises(DialException) as excinfo:
        await _client().delete(url)

    assert excinfo.value.status_code == 400
    assert httpx_mock.get_requests() == []


@pytest.mark.asyncio
async def test_file_etag_of_an_empty_file_comes_from_the_416(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/v2/{FILE_URL}",
        status_code=416,
        headers={"etag": "empty-file-etag"},
    )

    assert await _client().file_etag(FILE_URL) == "empty-file-etag"


@pytest.mark.asyncio
async def test_project_metadata_returns_the_body(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/v2/metadata/projects/b/My%20Project",
        json={"name": "My Project", "etag": "e"},
    )

    assert await _client().project_metadata("projects/b/My%20Project") == {
        "name": "My Project",
        "etag": "e",
    }


@pytest.mark.asyncio
async def test_project_metadata_404_is_not_found(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET", url=f"{BASE_URL}/v2/metadata/projects/b/p", status_code=404
    )

    with pytest.raises(ResourceNotFoundError):
        await _client().project_metadata("projects/b/p")
