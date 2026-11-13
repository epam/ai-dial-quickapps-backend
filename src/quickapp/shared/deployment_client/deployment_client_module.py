from injector import Module, provider
from openai.lib.azure import AsyncAzureOpenAI

from quickapp.common import DEPLOYMENT_AZURE_CLIENT, DIAL_API_KEY, DIAL_BEARER, ForwardedHeaders
from quickapp.common.dial_settings import DialSettings
from quickapp.common.tool_timeout_utils import build_async_dial_timeout
from quickapp.shared.config_resolvers.tool_timeout_resolver import ToolTimeoutResolver


class DeploymentClientModule(Module):
    """Provides the unpinned DIAL client (any deployment may be addressed per call).

    Shared by DIAL deployment tools and the tool-discovery routing call, so neither feature
    module depends on the other being installed.
    """

    @provider
    def provide_deployment_openai_client(
        self,
        dial_settings: DialSettings,
        api_key: DIAL_API_KEY,
        forwarded_headers: ForwardedHeaders,
        timeout_resolver: ToolTimeoutResolver,
        bearer: DIAL_BEARER,
    ) -> DEPLOYMENT_AZURE_CLIENT:
        headers = dict(forwarded_headers or {})

        if bearer:
            headers["Authorization"] = f"Bearer {bearer.get_secret_value()}"

        return AsyncAzureOpenAI(
            azure_endpoint=dial_settings.url,
            api_key=api_key.get_secret_value(),
            api_version=dial_settings.api_version,
            default_headers=headers,
            timeout=build_async_dial_timeout(timeout_resolver.resolve()),
        )
