from aidial_sdk.application import DIALApp
from aidial_sdk.chat_completion import ChatCompletion
from aidial_sdk.telemetry.types import TelemetryConfig
from fastapi_injector import InjectorMiddleware, RequestScopeOptions, attach_injector
from injector import Injector, inject

from quickapp.application._otel_settings import _OtelSettings
from quickapp.common.dial_settings import DialSettings


# The _QuickAppApplication class extends DIALApp to create a FastAPI-based application
# with dependency injection support and set request handling delegation to the completion. It:
# - Adds InjectorMiddleware and attaches the injector to the FastAPI for per-request dependency management
# - Configures the application and registers a chat completion
@inject
class _QuickAppApplication(DIALApp):
    def __init__(
        self,
        injector: Injector,
        completion: ChatCompletion,
        dial_settings: DialSettings,
        otel_settings: _OtelSettings,
    ):
        super().__init__(
            dial_url=dial_settings.url,
            propagate_auth_headers=True,
            add_healthcheck=True,
            telemetry_config=TelemetryConfig(service_name=otel_settings.service_name),
        )
        # noinspection PyTypeChecker
        self.add_middleware(InjectorMiddleware, injector=injector)
        attach_injector(self, injector, RequestScopeOptions())
        self.add_chat_completion("quick_apps2", completion)
