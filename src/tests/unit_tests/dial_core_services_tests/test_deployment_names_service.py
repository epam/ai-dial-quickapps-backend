import httpx
import pytest
from aidial_client import AsyncDial
from pydantic import ValidationError

from quickapp.dial_core_services.deployment_names_service import DeploymentNamesCoreService
from tests.unit_tests.common.common import make_provider

BASE_URL = "http://test-dial"
API_KEY = "test-api-key"


def _service() -> DeploymentNamesCoreService:
    client = AsyncDial(base_url=BASE_URL, api_key=API_KEY, max_retries=0)
    return DeploymentNamesCoreService(make_provider(client))


@pytest.mark.asyncio
async def test_lists_ids_from_deployment_names_endpoint(httpx_mock):
    httpx_mock.add_response(
        json=[
            {"id": "gpt-4", "object": "model"},
            {"id": "applications/bucket/my%20app", "object": "application"},
            {"id": "dial-mcp-toolset", "object": "toolset"},
        ]
    )

    names = await _service().list_names()

    assert names == ["gpt-4", "applications/bucket/my%20app", "dial-mcp-toolset"]
    request = httpx_mock.get_requests()[0]
    assert request.method == "GET"
    assert request.url.path == "/v1/deployment-names"
    assert request.url.params["type"] == "model,application,toolset"
    assert request.headers["Api-Key"] == API_KEY


@pytest.mark.asyncio
async def test_empty_list_means_nothing_is_accessible(httpx_mock):
    httpx_mock.add_response(json=[])

    assert await _service().list_names() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [403, 404, 500])
async def test_http_error_status_raises(httpx_mock, status_code):
    httpx_mock.add_response(status_code=status_code)

    with pytest.raises(httpx.HTTPStatusError):
        await _service().list_names()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [{"data": [{"id": "a", "object": "model"}]}, [{"name": "a"}], ["a"]],
    ids=["envelope", "missing-id", "bare-strings"],
)
async def test_unexpected_body_shape_raises_value_error(httpx_mock, body):
    httpx_mock.add_response(json=body)

    with pytest.raises(ValidationError):
        await _service().list_names()
