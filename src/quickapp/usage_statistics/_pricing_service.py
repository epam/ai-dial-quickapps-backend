import logging
from datetime import timedelta

from injector import inject

from quickapp.common import DIAL_API_KEY
from quickapp.common.dial_core_client import DialCoreClient
from quickapp.common.dial_settings import DialSettings
from quickapp.usage_statistics._pricing import _Pricing
from quickapp.usage_statistics._pricing_registry import _PricingRegistry

logger = logging.getLogger(__name__)


@inject
class _PricingService:
    VALID_PRICING_EXPIRATION_WINDOW: timedelta = timedelta(days=1)
    ERROR_PRICING_EXPIRATION_WINDOW: timedelta = timedelta(minutes=10)

    def __init__(
        self,
        pricing_registry: _PricingRegistry,
        dial_settings: DialSettings,
        api_key: DIAL_API_KEY,
    ):
        self.__pricing_registry: _PricingRegistry = pricing_registry
        self.__dial_settings: DialSettings = dial_settings
        self.__api_key: DIAL_API_KEY = api_key

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
            async with DialCoreClient(
                api_key=self.__api_key, base_url=self.__dial_settings.url
            ) as dial_core:
                json_response = await dial_core.get_model_pricing(model_name)
                fetched_pricing = json_response.get("pricing")

                if not fetched_pricing:
                    return _Pricing()

                return _Pricing(
                    input_token_price=float(fetched_pricing.get("prompt")),
                    output_token_price=float(fetched_pricing.get("completion")),
                )
        except Exception:
            logging.exception(f"Exception while fetching pricing for model {model_name}")
            return _Pricing()
