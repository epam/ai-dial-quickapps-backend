from fastapi_injector import request_scope
from injector import Binder, Module, singleton

from quickapp.usage_statistics._pricing_registry import _PricingRegistry
from quickapp.usage_statistics._pricing_service import _PricingService
from quickapp.usage_statistics.usage_statistics_service import UsageStatisticsService


class UsageStatisticsModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_PricingRegistry, to=_PricingRegistry, scope=singleton)
        binder.bind(_PricingService, to=_PricingService, scope=request_scope)
        binder.bind(UsageStatisticsService, to=UsageStatisticsService, scope=request_scope)
