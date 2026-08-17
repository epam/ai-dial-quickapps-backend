"""
Integration tests for AsyncDial HTTP calls.

These tests verify that service classes issue the correct HTTP requests via a
real AsyncDial client.  All outbound HTTP traffic is intercepted by
pytest-httpx so no running DIAL server is required.

Coverage:
  - ToolConfigCoreService: deployments.get, application.get,
    deployments.get_configuration_schema, toolset.get
  - DialDownloader: files.get_metadata, files.download
  - DialFileService:  resource_permissions.grant
  - AttachmentService: bucket.get_raw, files.upload
  - _PricingService:  model.get
"""

import json
from unittest.mock import MagicMock

import pytest
from aidial_client import AsyncDial
from aidial_client.types.toolset import ToolsetInfo
from injector import ProviderOf
from pydantic import SecretStr

from quickapp.common.dial_settings import DialSettings
from quickapp.common.state_holder import StateHolder
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_core_services.dial_downloader import DialDownloader
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.dial_core_services.exceptions import (
    ToolsetForbiddenException,
    ToolsetNotFoundException,
)
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService
from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
)
from quickapp.usage_statistics._pricing_registry import _PricingRegistry
from quickapp.usage_statistics._pricing_service import _PricingService
from tests.unit_tests.common.common import noop_timeout_resolver_provider

# ---------------------------------------------------------------------------
# Shared test configuration
# ---------------------------------------------------------------------------

BASE_URL = "http://test-dial"
API_KEY = "test-api-key"

# Minimal valid DIAL API responses ------------------------------------------------

_DEPLOYMENT_RESP = {
    "id": "test-model",
    "model": "test-model",
    "object": "deployment",
    "description": "A test deployment",
    "created_at": 1_700_000_000,
    "features": {"configuration": False},
}

_APPLICATION_RESP = {
    "id": "test-app",
    "application": "test-app",
    "object": "application",
    "description": "A test application",
    "created_at": 1_700_000_000,
}

_TOOLSET_RESP = {
    "id": "test-toolset",
    "toolset": "test-toolset",
    "description": "A test toolset",
}

_BUCKET_RESP = {"bucket": "my-bucket"}

_FILE_METADATA_RESP = {
    "name": "test.txt",
    "parentPath": None,
    "bucket": "my-bucket",
    "url": "files/my-bucket/test.txt",
    "nodeType": "ITEM",
    "resourceType": "FILE",
    "contentLength": 100,
}

_FILE_UPLOAD_RESP = {
    "name": "test.txt",
    "parentPath": None,
    "bucket": "my-bucket",
    "url": "files/my-bucket/test.txt",
    "nodeType": "ITEM",
    "resourceType": "FILE",
    "contentLength": 5,
}

_MODEL_INFO_RESP = {
    "id": "test-model",
    "model": "test-model",
    "pricing": {
        "unit": "token",
        "prompt": "0.001",
        "completion": "0.002",
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dial_client() -> AsyncDial:
    """Create a real AsyncDial with 0 retries so mock responses are consumed once."""
    return AsyncDial(base_url=BASE_URL, api_key=API_KEY, max_retries=0)


def _provider(client: AsyncDial) -> MagicMock:
    provider = MagicMock(spec=ProviderOf)
    provider.get.return_value = client
    return provider


def _file_loading_size_limit_resolver(size_limit: int = 10 * 1024 * 1024) -> MagicMock:
    resolver = MagicMock(spec=FileLoadingSizeLimitResolver)
    resolver.resolve.return_value = size_limit
    return resolver


def _dial_settings() -> DialSettings:
    return DialSettings(url=BASE_URL)


def _tool_config_service(client: AsyncDial) -> ToolConfigCoreService:
    return ToolConfigCoreService(
        dial_settings=_dial_settings(),
        dial_client_provider=_provider(client),
        timeout_resolver_provider=noop_timeout_resolver_provider(),
        default_locale="en",
    )


# ---------------------------------------------------------------------------
# ToolConfigCoreService – AsyncDial HTTP calls
# ---------------------------------------------------------------------------


class TestToolConfigServiceHttpCalls:
    """Verify the HTTP requests made by ToolConfigCoreService via AsyncDial."""

    @pytest.mark.asyncio
    async def test_deployment_path_calls_deployments_get(self, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/openai/deployments/test-model",
            json=_DEPLOYMENT_RESP,
        )

        result = await _tool_config_service(_dial_client()).get_basic_tool_config("test-model")

        assert result.deployment.deployment_id == "test-model"
        requests = httpx_mock.get_requests()
        assert len(requests) == 1
        assert "openai/deployments/test-model" in str(requests[0].url)

    @pytest.mark.asyncio
    async def test_404_on_deployment_falls_back_to_application_get(self, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/openai/deployments/test-app",
            status_code=404,
            json={"error": {"code": "404", "message": "Not found", "type": "not_found"}},
        )
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/openai/applications/test-app",
            json=_APPLICATION_RESP,
        )

        result = await _tool_config_service(_dial_client()).get_basic_tool_config("test-app")

        assert result.deployment.deployment_id == "test-app"
        urls = [str(r.url) for r in httpx_mock.get_requests()]
        assert any("openai/deployments/test-app" in u for u in urls)
        assert any("openai/applications/test-app" in u for u in urls)

    @pytest.mark.asyncio
    async def test_deployment_with_configuration_calls_schema_endpoint(self, httpx_mock):
        dep_with_config = {**_DEPLOYMENT_RESP, "features": {"configuration": True}}
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/openai/deployments/configurable-dep",
            json=dep_with_config,
        )
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/v1/deployments/configurable-dep/configuration",
            json={
                "type": "object",
                "properties": {
                    "language": {"type": "string", "description": "Language to use"},
                },
                "required": ["language"],
            },
        )

        result = await _tool_config_service(_dial_client()).get_basic_tool_config(
            "configurable-dep"
        )

        assert "language" in result.open_ai_tool.function.parameters.properties
        assert "language" in result.open_ai_tool.function.parameters.required
        urls = [str(r.url) for r in httpx_mock.get_requests()]
        assert any("configuration" in u for u in urls)

    @pytest.mark.asyncio
    async def test_explicit_api_key_creates_fresh_dial_client_and_skips_provider(self, httpx_mock):
        """When api_key is passed, a new AsyncDial is created inline – DI provider unused."""
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/openai/deployments/test-model",
            json=_DEPLOYMENT_RESP,
        )

        provider = MagicMock(spec=ProviderOf)
        svc = ToolConfigCoreService(
            dial_settings=_dial_settings(),
            dial_client_provider=provider,
            timeout_resolver_provider=noop_timeout_resolver_provider(),
            default_locale="en",
        )
        result = await svc.get_basic_tool_config("test-model", api_key=SecretStr(API_KEY))

        assert result.deployment.deployment_id == "test-model"
        provider.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_toolset_get_calls_toolsets_endpoint(self, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/openai/toolsets/test-toolset",
            json=_TOOLSET_RESP,
        )

        result = await _tool_config_service(_dial_client()).get_basic_toolset_config("test-toolset")

        assert isinstance(result, ToolsetInfo)
        assert result.id == "test-toolset"
        requests = httpx_mock.get_requests()
        assert len(requests) == 1
        assert "openai/toolsets/test-toolset" in str(requests[0].url)

    @pytest.mark.asyncio
    async def test_toolset_404_raises_toolset_not_found_exception(self, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/openai/toolsets/missing",
            status_code=404,
            json={"error": {"code": "404", "message": "Not found", "type": "not_found"}},
        )

        with pytest.raises(ToolsetNotFoundException):
            await _tool_config_service(_dial_client()).get_basic_toolset_config("missing")

    @pytest.mark.asyncio
    async def test_toolset_403_raises_toolset_forbidden_exception(self, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/openai/toolsets/forbidden",
            status_code=403,
            json={"error": {"code": "403", "message": "Forbidden", "type": "forbidden"}},
        )

        with pytest.raises(ToolsetForbiddenException):
            await _tool_config_service(_dial_client()).get_basic_toolset_config("forbidden")


# ---------------------------------------------------------------------------
# DialDownloader / DialFileService – AsyncDial HTTP calls
# ---------------------------------------------------------------------------


class TestDialFileServiceHttpCalls:
    """Verify the HTTP requests made by DialDownloader / DialFileService via AsyncDial."""

    @pytest.mark.asyncio
    async def test_download_file_calls_metadata_then_download(self, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/v1/metadata/files/my-bucket/test.txt",
            json=_FILE_METADATA_RESP,
        )
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/v1/files/my-bucket/test.txt",
            content=b"hello world",
        )

        downloader = DialDownloader(
            dial_client=_dial_client(),
            size_limit_resolver=_file_loading_size_limit_resolver(),
        )
        data, metadata = await downloader.fetch("files/my-bucket/test.txt")

        assert data == b"hello world"
        assert metadata is not None
        urls = [str(r.url) for r in httpx_mock.get_requests()]
        assert any("v1/metadata/files/my-bucket/test.txt" in u for u in urls)
        assert any("v1/files/my-bucket/test.txt" in u for u in urls)

    @pytest.mark.asyncio
    async def test_download_file_exceeding_size_limit_does_not_call_download(self, httpx_mock):
        large_metadata = {**_FILE_METADATA_RESP, "contentLength": 11 * 1024 * 1024}
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/v1/metadata/files/my-bucket/large.bin",
            json={**large_metadata, "name": "large.bin", "url": "files/my-bucket/large.bin"},
        )

        downloader = DialDownloader(
            dial_client=_dial_client(),
            size_limit_resolver=_file_loading_size_limit_resolver(),
        )
        with pytest.raises(ValueError, match="exceeds the limit"):
            await downloader.fetch("files/my-bucket/large.bin")

        requests = httpx_mock.get_requests()
        assert len(requests) == 1, "download must NOT be called when metadata rejects the file"
        assert "v1/metadata" in str(requests[0].url)

    @pytest.mark.asyncio
    async def test_grant_permissions_calls_correct_endpoint_with_expected_body(self, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url=f"{BASE_URL}/v1/ops/resource/per-request-permissions/grant",
            status_code=200,
        )

        svc = DialFileService(
            dial_client=_dial_client(),
            state_holder=StateHolder(),
            size_limit_resolver=_file_loading_size_limit_resolver(),
        )
        await svc.grant_permissions_to_files(
            ["files/my-bucket/a.txt", "files/my-bucket/b.txt"],
            "my-toolset",
        )

        requests = httpx_mock.get_requests()
        assert len(requests) == 1
        req = requests[0]
        assert req.method == "POST"
        assert "per-request-permissions/grant" in str(req.url)
        body = json.loads(req.content)
        assert body["receiver"] == "my-toolset"
        resource_urls = [r["url"] for r in body["resourcePermissions"]]
        assert "files/my-bucket/a.txt" in resource_urls
        assert "files/my-bucket/b.txt" in resource_urls


# ---------------------------------------------------------------------------
# AttachmentService – AsyncDial HTTP calls
# ---------------------------------------------------------------------------


class TestAttachmentServiceHttpCalls:
    """Verify the HTTP requests made by AttachmentService via AsyncDial."""

    @pytest.mark.asyncio
    async def test_upload_attachment_calls_bucket_then_files_upload(self, httpx_mock):
        import base64

        from aidial_sdk.chat_completion import Attachment

        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/v1/bucket",
            json=_BUCKET_RESP,
        )
        httpx_mock.add_response(
            method="PUT",
            url=f"{BASE_URL}/v1/files/my-bucket/test.txt",
            json=_FILE_UPLOAD_RESP,
        )

        attachment = Attachment(
            title="test.txt",
            url=None,
            data=base64.b64encode(b"hello").decode(),
            type="text/plain",
        )

        svc = AttachmentService(dial_client=_dial_client())
        result = await svc.upload_attachment_to_core(attachment)

        assert result.url == "files/my-bucket/test.txt"
        assert result.data is None

        urls = [str(r.url) for r in httpx_mock.get_requests()]
        assert any("v1/bucket" in u for u in urls)
        assert any("v1/files/my-bucket/test.txt" in u for u in urls)

    @pytest.mark.asyncio
    async def test_upload_skipped_when_url_already_set_no_http_calls_made(self, httpx_mock):
        from aidial_sdk.chat_completion import Attachment

        attachment = Attachment(
            title="test.txt",
            url="https://already-exists.com/file",
            data=None,
            type="text/plain",
        )

        svc = AttachmentService(dial_client=_dial_client())
        result = await svc.upload_attachment_to_core(attachment)

        assert result.url == "https://already-exists.com/file"
        assert httpx_mock.get_requests() == []


# ---------------------------------------------------------------------------
# _PricingService – AsyncDial HTTP calls
# ---------------------------------------------------------------------------


class TestPricingServiceHttpCalls:
    """Verify the HTTP requests made by _PricingService via AsyncDial."""

    @pytest.mark.asyncio
    async def test_get_price_calls_models_endpoint_and_parses_pricing(self, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/openai/models/test-model",
            json=_MODEL_INFO_RESP,
        )

        svc = _PricingService(
            pricing_registry=_PricingRegistry(),
            dial_client=_dial_client(),
        )
        pricing = await svc.get_price("test-model")

        assert pricing.input_token_price == pytest.approx(0.001)
        assert pricing.output_token_price == pytest.approx(0.002)
        requests = httpx_mock.get_requests()
        assert len(requests) == 1
        assert "openai/models/test-model" in str(requests[0].url)

    @pytest.mark.asyncio
    async def test_get_price_with_no_pricing_field_returns_empty_pricing(self, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/openai/models/test-model",
            json={**_MODEL_INFO_RESP, "pricing": None},
        )

        svc = _PricingService(
            pricing_registry=_PricingRegistry(),
            dial_client=_dial_client(),
        )
        pricing = await svc.get_price("test-model")

        # _Pricing() defaults to "-" sentinel – not a numeric value
        assert pricing.input_token_price == "-"
        assert pricing.output_token_price == "-"

    @pytest.mark.asyncio
    async def test_get_price_is_cached_after_first_fetch(self, httpx_mock):
        """Second call must not hit the API again."""
        httpx_mock.add_response(
            method="GET",
            url=f"{BASE_URL}/openai/models/test-model",
            json=_MODEL_INFO_RESP,
        )

        registry = _PricingRegistry()
        svc = _PricingService(pricing_registry=registry, dial_client=_dial_client())

        await svc.get_price("test-model")
        # Second call must re-use the shared dial_client but registry is separate per svc,
        # so create the same registry instance for the second service to prove caching.
        svc2 = _PricingService(pricing_registry=registry, dial_client=_dial_client())
        await svc2.get_price("test-model")

        # Only one HTTP call expected because the second service shares the registry
        assert len(httpx_mock.get_requests()) == 1
