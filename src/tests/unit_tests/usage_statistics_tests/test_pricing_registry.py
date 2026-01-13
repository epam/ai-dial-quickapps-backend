import unittest
from unittest.mock import MagicMock
# noinspection PyProtectedMember
from quickapp.usage_statistics._pricing_registry import _PricingRegistry
# noinspection PyProtectedMember
from quickapp.usage_statistics._pricing import _Pricing


class TestPricingRegistry(unittest.TestCase):

    def setUp(self):
        self.registry = _PricingRegistry()

    def test_get_model_pricing_returns_pricing_if_not_expired(self):
        mock_pricing = MagicMock(spec=_Pricing)
        mock_pricing.is_expired.return_value = False
        self.registry.set_model_pricing("test_model", mock_pricing)

        result = self.registry.get_model_pricing("test_model")

        self.assertIs(result, mock_pricing)
        mock_pricing.is_expired.assert_called_once()

    def test_get_model_pricing_returns_none_if_expired(self):
        mock_pricing = MagicMock(spec=_Pricing)
        mock_pricing.is_expired.return_value = True
        self.registry.set_model_pricing("test_model", mock_pricing)

        result = self.registry.get_model_pricing("test_model")

        self.assertIsNone(result)
        mock_pricing.is_expired.assert_called_once()

    def test_get_model_pricing_returns_none_if_not_in_cache(self):
        result = self.registry.get_model_pricing("nonexistent_model")
        self.assertIsNone(result)

if __name__ == "__main__":
    unittest.main()