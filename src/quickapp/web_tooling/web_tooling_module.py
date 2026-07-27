import logging

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider

from quickapp.common import StagedBaseTool
from quickapp.common.exceptions import InitializationException, ToolInitializationException
from quickapp.common.preview import preview_module
from quickapp.config.application import ApplicationConfig
from quickapp.config.web_fetch import WebFetchConfig
from quickapp.shared.external_fetch.external_url_fetch_policy_resolver import (
    ExternalUrlFetchPolicyResolver,
)
from quickapp.web_tooling._tool_configs import WEB_FETCH_TOOL_CONFIG
from quickapp.web_tooling._web_fetch_stage_wrapper import _WebFetchStageWrapper
from quickapp.web_tooling._web_fetch_tool import _WebFetchTool

logger = logging.getLogger(__name__)

_EGRESS_DISABLED_MESSAGE = (
    "internal_web_fetch requires external URL fetching, which is disabled. Enable it "
    "via the admin switch EXTERNAL_URL_FETCH_ENABLED and do not set "
    "features.external_url_fetch.enabled=false, or remove features.web_fetch."
)


@preview_module
class WebToolingModule(Module):
    """Built-in web tools. Currently the single ``internal_web_fetch`` tool.

    Preview-gated at the module level; ``features.web_fetch`` is itself a
    ``PreviewField``. Kept separate from the DIAL-files family because it writes
    no file (a plain ``StagedBaseTool``, not a ``_DialFileTool``).

    The tool cannot function without external egress, so it is gated on the egress
    policy at initialization: if ``features.web_fetch.enabled`` is set while external
    fetching is disabled (admin cap or per-app opt-out), the tool is **not** exposed
    and a hard ``ToolInitializationException`` surfaces the contradictory config —
    rather than exposing a tool that would fail on every call.
    """

    def configure(self, binder: Binder) -> None:
        binder.bind(_WebFetchStageWrapper, to=_WebFetchStageWrapper, scope=request_scope)
        binder.bind(_WebFetchTool, to=_WebFetchTool, scope=request_scope)
        logger.debug("WebToolingModule configuration completed")

    @staticmethod
    def _web_fetch_config(app_config: ApplicationConfig) -> WebFetchConfig | None:
        features = app_config.features
        return features.web_fetch if features else None

    @multiprovider
    def _provide_web_fetch_tools(
        self,
        app_config: ApplicationConfig,
        policy: ExternalUrlFetchPolicyResolver,
        tool_builder: AssistedBuilder[_WebFetchTool],
    ) -> list[StagedBaseTool]:
        cfg = self._web_fetch_config(app_config)
        # Not requested, or requested while egress is disabled (surfaced as an
        # initialization error below): keep the tool unexposed either way.
        if cfg is None or not cfg.enabled or not policy.is_enabled():
            return []

        return [
            tool_builder.build(
                tool_config=WEB_FETCH_TOOL_CONFIG,
                name=WEB_FETCH_TOOL_CONFIG.open_ai_tool.function.name,
                description=WEB_FETCH_TOOL_CONFIG.open_ai_tool.function.description,
                max_inline_size=cfg.max_inline_size,
            )
        ]

    @multiprovider
    def _provide_initialization_exceptions(
        self,
        app_config: ApplicationConfig,
        policy: ExternalUrlFetchPolicyResolver,
    ) -> list[InitializationException]:
        cfg = self._web_fetch_config(app_config)
        if cfg is not None and cfg.enabled and not policy.is_enabled():
            return [
                ToolInitializationException(
                    _EGRESS_DISABLED_MESSAGE,
                    tool_name=WEB_FETCH_TOOL_CONFIG.open_ai_tool.function.name,
                )
            ]
        return []
