from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from quickapp.common import DIAL_API_KEY
from quickapp.common.dial_core_client import DialCoreClient
from quickapp.common.dial_settings import DialSettings
# noinspection PyProtectedMember
from quickapp.usage_statistics._pricing import _Pricing
# noinspection PyProtectedMember
from quickapp.usage_statistics._pricing_registry import _PricingRegistry
# noinspection PyProtectedMember
from quickapp.usage_statistics._pricing_service import _PricingService


@pytest.fixture
def mock_registry():
    registry = MagicMock(spec=_PricingRegistry)
    registry.get_model_pricing.return_value = None
    return registry


@pytest.fixture
def mock_dial_settings():
    settings = MagicMock(spec=DialSettings)
    settings.url = "https://api.example.com"
    return settings


@pytest.fixture
def mock_api_key():
    api_key = MagicMock(spec=DIAL_API_KEY)
    api_key.get_secret_value.return_value = "test-api-key"
    return api_key


@pytest.fixture
def pricing_service(mock_registry, mock_dial_settings, mock_api_key):
    return _PricingService(mock_registry, mock_dial_settings, mock_api_key)


@pytest.mark.asyncio
async def test_get_price_from_cache(pricing_service, mock_registry):
    # Setup
    mock_pricing = MagicMock(spec=_Pricing)
    mock_pricing.is_expired.return_value = False
    mock_registry.get_model_pricing.return_value = mock_pricing

    # Execute
    result = await pricing_service.get_price("gpt-4")

    # Verify
    mock_registry.get_model_pricing.assert_called_once_with("gpt-4")
    assert result == mock_pricing
    mock_registry.set_model_pricing.assert_not_called()


@pytest.mark.asyncio
async def test_get_price_fetch_from_api(pricing_service, mock_registry):
    # Mock JSON response (simulating the response body from the API)
    mock_response = MagicMock()
    mock_response.json = MagicMock(return_value={
        "pricing": {
            "prompt": "0.01",
            "completion": "0.02",
        }
    })
    mock_response.raise_for_status = MagicMock()

    # Patch DialCoreClient to call real __aenter__ but mock self._client.get
    with patch("quickapp.common.dial_core_client.DialCoreClient.__aenter__", autospec=True) as mock_aenter:
        # Create a real DialCoreClient instance (or mock with spec)
        client_instance = DialCoreClient(api_key="testkey", base_url="http://test")

        # Setup mock for self._client inside client_instance
        client_instance._client = MagicMock()
        client_instance._client.get = AsyncMock(return_value=mock_response)

        # Make __aenter__ return our client instance with mocked _client
        mock_aenter.return_value = client_instance

        # Call your method under test
        result = await pricing_service.get_price("gpt-4")

        # Assertions
        mock_registry.get_model_pricing.assert_called_once_with("gpt-4")
        mock_registry.set_model_pricing.assert_called_once()
        assert isinstance(result, _Pricing)
        assert result.input_token_price == 0.01
        assert result.output_token_price == 0.02


@pytest.mark.asyncio
async def test_get_price_api_error(pricing_service, mock_registry):
    # Setup
    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.get.side_effect = aiohttp.ClientError("API Error")

    # Execute
    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await pricing_service.get_price("gpt-4")

    # Verify
    mock_registry.get_model_pricing.assert_called_once_with("gpt-4")
    assert isinstance(result, _Pricing)
    assert result.input_token_price == "-"
    assert result.output_token_price == "-"


@pytest.mark.asyncio
async def test_get_price_missing_pricing_data(pricing_service, mock_registry):
    # Setup - API returns response without pricing data
    mock_response = AsyncMock()
    mock_response.raise_for_status = AsyncMock()
    mock_response.json = AsyncMock(return_value={})  # No pricing data

    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.get.return_value.__aenter__.return_value = mock_response

    # Execute
    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await pricing_service.get_price("gpt-4")

    # Verify
    mock_registry.get_model_pricing.assert_called_once_with("gpt-4")
    assert isinstance(result, _Pricing)
    assert result.input_token_price == "-"
    assert result.output_token_price == "-"

@pytest.mark.asyncio
async def test_get_price_http_error(pricing_service, mock_registry):
    # Setup - HTTP error response
    mock_response = AsyncMock()
    mock_response.raise_for_status = AsyncMock(side_effect=aiohttp.ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=404
    ))

    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.get.return_value.__aenter__.return_value = mock_response

    # Execute
    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await pricing_service.get_price("unknown-model")

    # Verify
    mock_registry.get_model_pricing.assert_called_once_with("unknown-model")
    assert isinstance(result, _Pricing)
    assert result.input_token_price == "-"
    assert result.output_token_price == "-"