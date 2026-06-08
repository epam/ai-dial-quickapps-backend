from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.usage_statistics._pricing import _Pricing
from quickapp.usage_statistics._pricing_registry import _PricingRegistry
from quickapp.usage_statistics._pricing_service import _PricingService


def _make_model_info(prompt: str | None = "0.01", completion: str | None = "0.02") -> MagicMock:
    if prompt is None and completion is None:
        model_info = MagicMock()
        model_info.pricing = None
        return model_info

    pricing = MagicMock()
    pricing.prompt = prompt
    pricing.completion = completion

    model_info = MagicMock()
    model_info.pricing = pricing
    return model_info


def _make_service(
    registry: _PricingRegistry | None = None,
    model_info: MagicMock | None = None,
    model_side_effect: Exception | None = None,
) -> tuple[_PricingService, MagicMock]:
    mock_registry = registry or MagicMock(spec=_PricingRegistry)
    if not hasattr(mock_registry, "get_model_pricing") or not callable(
        mock_registry.get_model_pricing
    ):
        mock_registry.get_model_pricing.return_value = None

    mock_model = MagicMock()
    mock_model.get = AsyncMock(return_value=model_info, side_effect=model_side_effect)

    mock_dial_client = MagicMock()
    mock_dial_client.model = mock_model

    return _PricingService(mock_registry, mock_dial_client), mock_dial_client


@pytest.mark.asyncio
async def test_get_price_from_cache():
    cached = MagicMock(spec=_Pricing)
    cached.is_expired.return_value = False

    registry = MagicMock(spec=_PricingRegistry)
    registry.get_model_pricing.return_value = cached

    svc, mock_dial_client = _make_service(registry=registry)

    result = await svc.get_price("gpt-4")

    assert result is cached
    mock_dial_client.model.get.assert_not_called()
    registry.set_model_pricing.assert_not_called()


@pytest.mark.asyncio
async def test_get_price_fetch_from_api():
    registry = MagicMock(spec=_PricingRegistry)
    registry.get_model_pricing.return_value = None

    svc, mock_dial_client = _make_service(
        registry=registry,
        model_info=_make_model_info(prompt="0.01", completion="0.02"),
    )

    result = await svc.get_price("gpt-4")

    mock_dial_client.model.get.assert_awaited_once_with("gpt-4")
    registry.set_model_pricing.assert_called_once()
    assert isinstance(result, _Pricing)
    assert result.input_token_price == 0.01
    assert result.output_token_price == 0.02


@pytest.mark.asyncio
async def test_get_price_missing_pricing_data():
    registry = MagicMock(spec=_PricingRegistry)
    registry.get_model_pricing.return_value = None

    svc, _ = _make_service(registry=registry, model_info=_make_model_info(None, None))

    result = await svc.get_price("gpt-4")

    assert isinstance(result, _Pricing)
    assert result.input_token_price == "-"
    assert result.output_token_price == "-"


@pytest.mark.asyncio
async def test_get_price_api_error_returns_empty_pricing():
    registry = MagicMock(spec=_PricingRegistry)
    registry.get_model_pricing.return_value = None

    svc, _ = _make_service(registry=registry, model_side_effect=Exception("API error"))

    result = await svc.get_price("gpt-4")

    assert isinstance(result, _Pricing)
    assert result.input_token_price == "-"
    assert result.output_token_price == "-"
