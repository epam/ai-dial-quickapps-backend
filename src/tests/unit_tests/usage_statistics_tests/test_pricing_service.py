from unittest.mock import AsyncMock, MagicMock

import pytest

# noinspection PyProtectedMember
from quickapp.usage_statistics._pricing import _Pricing

# noinspection PyProtectedMember
from quickapp.usage_statistics._pricing_registry import _PricingRegistry

# noinspection PyProtectedMember
from quickapp.usage_statistics._pricing_service import _PricingService
from tests.unit_tests.common.common import mock_dial_core_client_factory


@pytest.fixture
def mock_registry():
    registry = MagicMock(spec=_PricingRegistry)
    registry.get_model_pricing.return_value = None
    return registry


@pytest.mark.asyncio
async def test_get_price_from_cache(mock_registry):
    mock_pricing = MagicMock(spec=_Pricing)
    mock_pricing.is_expired.return_value = False
    mock_registry.get_model_pricing.return_value = mock_pricing

    factory = MagicMock()
    svc = _PricingService(mock_registry, factory)
    result = await svc.get_price("gpt-4")

    mock_registry.get_model_pricing.assert_called_once_with("gpt-4")
    assert result == mock_pricing
    mock_registry.set_model_pricing.assert_not_called()
    factory.create.assert_not_called()


@pytest.mark.asyncio
async def test_get_price_fetch_from_api(mock_registry):
    mock_client = AsyncMock()
    mock_client.get_model_pricing.return_value = {
        "pricing": {"prompt": "0.01", "completion": "0.02"}
    }
    factory, _ = mock_dial_core_client_factory(mock_client)

    svc = _PricingService(mock_registry, factory)
    result = await svc.get_price("gpt-4")

    mock_registry.get_model_pricing.assert_called_once_with("gpt-4")
    mock_registry.set_model_pricing.assert_called_once()
    assert isinstance(result, _Pricing)
    assert result.input_token_price == 0.01
    assert result.output_token_price == 0.02


@pytest.mark.asyncio
async def test_get_price_api_error(mock_registry):
    mock_client = AsyncMock()
    mock_client.get_model_pricing.side_effect = Exception("API Error")
    factory, _ = mock_dial_core_client_factory(mock_client)

    svc = _PricingService(mock_registry, factory)
    result = await svc.get_price("gpt-4")

    mock_registry.get_model_pricing.assert_called_once_with("gpt-4")
    assert isinstance(result, _Pricing)
    assert result.input_token_price == "-"
    assert result.output_token_price == "-"


@pytest.mark.asyncio
async def test_get_price_missing_pricing_data(mock_registry):
    mock_client = AsyncMock()
    mock_client.get_model_pricing.return_value = {}
    factory, _ = mock_dial_core_client_factory(mock_client)

    svc = _PricingService(mock_registry, factory)
    result = await svc.get_price("gpt-4")

    mock_registry.get_model_pricing.assert_called_once_with("gpt-4")
    assert isinstance(result, _Pricing)
    assert result.input_token_price == "-"
    assert result.output_token_price == "-"


@pytest.mark.asyncio
async def test_get_price_http_error(mock_registry):
    mock_client = AsyncMock()
    mock_client.get_model_pricing.side_effect = Exception("Not Found")
    factory, _ = mock_dial_core_client_factory(mock_client)

    svc = _PricingService(mock_registry, factory)
    result = await svc.get_price("unknown-model")

    mock_registry.get_model_pricing.assert_called_once_with("unknown-model")
    assert isinstance(result, _Pricing)
    assert result.input_token_price == "-"
    assert result.output_token_price == "-"
