from unittest.mock import MagicMock

import pytest

# noinspection PyProtectedMember
from quickapp.usage_statistics._pricing import _Pricing

# noinspection PyProtectedMember
from quickapp.usage_statistics._pricing_registry import _PricingRegistry


@pytest.fixture
def registry():
    return _PricingRegistry()


def test_get_model_pricing_returns_pricing_if_not_expired(registry):
    mock_pricing = MagicMock(spec=_Pricing)
    mock_pricing.is_expired.return_value = False
    registry.set_model_pricing("test_model", mock_pricing)

    result = registry.get_model_pricing("test_model")

    assert result is mock_pricing
    mock_pricing.is_expired.assert_called_once()


def test_get_model_pricing_returns_none_if_expired(registry):
    mock_pricing = MagicMock(spec=_Pricing)
    mock_pricing.is_expired.return_value = True
    registry.set_model_pricing("test_model", mock_pricing)

    result = registry.get_model_pricing("test_model")

    assert result is None
    mock_pricing.is_expired.assert_called_once()


def test_get_model_pricing_returns_none_if_not_in_cache(registry):
    result = registry.get_model_pricing("nonexistent_model")
    assert result is None
