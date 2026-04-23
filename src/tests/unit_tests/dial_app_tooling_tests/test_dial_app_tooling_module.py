from unittest.mock import MagicMock

from quickapp.common.exceptions import ToolInitializationException
from quickapp.dial_app_tooling._dial_app_resolver_context import _DialAppResolverContext
from quickapp.dial_app_tooling.dial_app_tooling_module import DialAppToolingModule


def test_provide_initialization_exceptions_returns_context_list():
    module = DialAppToolingModule()
    context = _DialAppResolverContext()
    exc = ToolInitializationException(message="boom", toolset_name="t")
    context.append_exception(exc)

    result = module._DialAppToolingModule__provide_initialization_exceptions(context)  # type: ignore[attr-defined]

    assert result == [exc]


def test_provide_initializers_returns_resolver():
    module = DialAppToolingModule()
    resolver_instance = MagicMock()
    provider = MagicMock()
    provider.get.return_value = resolver_instance

    result = module._DialAppToolingModule__provide_initializers(provider)  # type: ignore[attr-defined]

    assert result == [resolver_instance]
    provider.get.assert_called_once()
