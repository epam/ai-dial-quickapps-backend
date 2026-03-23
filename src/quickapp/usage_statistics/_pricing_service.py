import logging
from datetime import timedelta

from aidial_client import AsyncDial
from injector import inject

from quickapp.usage_statistics._pricing import _Pricing
from quickapp.usage_statistics._pricing_registry import _PricingRegistry

logger = logging.getLogger(__name__)


@inject
class _PricingService:
    VALID_PRICING_EXPIRATION_WINDOW: timedelta = timedelta(days=1)
    ERROR_PRICING_EXPIRATION_WINDOW: timedelta = timedelta(minutes=10)

    def __init__(self, pricing_registry: _PricingRegistry, dial_client: AsyncDial):
        self.__pricing_registry: _PricingRegistry = pricing_registry
        self.__dial_client: AsyncDial = dial_client

    async def get_price(self, model_name: str) -> _Pricing:
        try:
            pricing = self.__pricing_registry.get_model_pricing(model_name)
            if pricing is None:
                pricing = await self.__fetch_pricing_from_api(model_name)
                self.__pricing_registry.set_model_pricing(model_name, pricing)

            return pricing

        except Exception as e:
            logging.exception(f"Error calculating price for model {model_name}: {str(e)}")
            return _Pricing()

    async def __fetch_pricing_from_api(self, model_name: str) -> _Pricing:
        try:
            model_info = await self.__dial_client.model.get(model_name)
            if not model_info.pricing:
                return _Pricing()

            return _Pricing(
                input_token_price=float(model_info.pricing.prompt),
                output_token_price=float(model_info.pricing.completion),
            )
        except Exception:
            logging.exception(f"Exception while fetching pricing for model {model_name}")
            return _Pricing()
