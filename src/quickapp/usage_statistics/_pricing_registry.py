from injector import inject

from ._pricing import _Pricing


@inject
class _PricingRegistry:

    def __init__(self):
        self.__pricing_cache: dict[str, _Pricing] = {}

    def get_model_pricing(self, model_name: str) -> _Pricing | None:
        if model_name in self.__pricing_cache:
            pricing = self.__pricing_cache[model_name]
            if not pricing.is_expired():
                return pricing
        return None

    def set_model_pricing(self, model_name: str, pricing: _Pricing) -> None:
        self.__pricing_cache[model_name] = pricing
