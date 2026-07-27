from unittest.mock import MagicMock

from quickapp.common.exceptions import ToolInitializationException
from quickapp.config.web_fetch import WebFetchConfig
from quickapp.web_tooling.web_tooling_module import WebToolingModule


def _app_config(web_fetch: WebFetchConfig | None) -> MagicMock:
    app_config = MagicMock()
    app_config.features = MagicMock()
    app_config.features.web_fetch = web_fetch
    return app_config


def _policy(enabled: bool = True) -> MagicMock:
    policy = MagicMock()
    policy.is_enabled.return_value = enabled
    return policy


def _build_tools(app_config: MagicMock, egress_enabled: bool = True) -> tuple:
    module = WebToolingModule()
    builder = MagicMock()
    built = MagicMock()
    builder.build.return_value = built
    tools = module._provide_web_fetch_tools(
        app_config=app_config, policy=_policy(egress_enabled), tool_builder=builder
    )
    return tools, builder, built


class TestWebToolingModuleGating:
    def test_enabled_provides_tool(self):
        tools, builder, built = _build_tools(_app_config(WebFetchConfig(enabled=True)))
        assert tools == [built]
        assert builder.build.call_args.kwargs["max_inline_size"] == WebFetchConfig().max_inline_size

    def test_disabled_provides_nothing(self):
        tools, _, _ = _build_tools(_app_config(WebFetchConfig(enabled=False)))
        assert tools == []

    def test_absent_config_provides_nothing(self):
        tools, _, _ = _build_tools(_app_config(None))
        assert tools == []

    def test_no_features_provides_nothing(self):
        app_config = MagicMock()
        app_config.features = None
        tools, _, _ = _build_tools(app_config)
        assert tools == []

    def test_custom_max_inline_size_passed_through(self):
        tools, builder, _ = _build_tools(
            _app_config(WebFetchConfig(enabled=True, max_inline_size=1234))
        )
        assert builder.build.call_args.kwargs["max_inline_size"] == 1234

    def test_module_is_preview(self):
        from quickapp.common.preview import is_preview_module

        assert is_preview_module(WebToolingModule())


class TestEgressGate:
    def test_enabled_but_egress_disabled_provides_nothing(self):
        tools, builder, _ = _build_tools(
            _app_config(WebFetchConfig(enabled=True)), egress_enabled=False
        )
        assert tools == []
        builder.build.assert_not_called()

    def test_enabled_but_egress_disabled_raises_initialization_error(self):
        module = WebToolingModule()
        errors = module._provide_initialization_exceptions(
            app_config=_app_config(WebFetchConfig(enabled=True)), policy=_policy(False)
        )
        assert len(errors) == 1
        assert isinstance(errors[0], ToolInitializationException)
        assert errors[0].is_hard
        assert errors[0].tool_name == "internal_web_fetch"

    def test_enabled_with_egress_enabled_has_no_initialization_error(self):
        module = WebToolingModule()
        errors = module._provide_initialization_exceptions(
            app_config=_app_config(WebFetchConfig(enabled=True)), policy=_policy(True)
        )
        assert errors == []

    def test_disabled_has_no_initialization_error_even_if_egress_disabled(self):
        module = WebToolingModule()
        errors = module._provide_initialization_exceptions(
            app_config=_app_config(WebFetchConfig(enabled=False)), policy=_policy(False)
        )
        assert errors == []
