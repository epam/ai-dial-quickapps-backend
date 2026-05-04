from unittest.mock import MagicMock

from injector import Binder, Injector

from quickapp.common.exceptions import InitializationException, ToolInitializationException
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


def test_resolver_exceptions_reach_init_exception_multibinding():
    """Regression: the multiprovider must bind under list[InitializationException]
    so resolver-captured exceptions reach _InitializationErrorHandler. A previous
    revision typed it as list[ToolInitializationException], which the injector
    treats as a separate binding key — the exceptions silently never made it to
    the error stage."""
    context = _DialAppResolverContext()
    seeded = ToolInitializationException(message="boom", toolset_name="t")
    context.append_exception(seeded)

    def configure(binder: Binder) -> None:
        binder.bind(_DialAppResolverContext, to=context)

    injector = Injector(modules=[DialAppToolingModule(), configure])
    exceptions = injector.get(list[InitializationException])

    assert len(exceptions) == 1
    assert exceptions[0] is seeded
