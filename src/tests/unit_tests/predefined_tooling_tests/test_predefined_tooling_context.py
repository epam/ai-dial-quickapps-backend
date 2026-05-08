from quickapp.common.exceptions import ConfigResolutionException
from quickapp.predefined_tooling._predefined_tooling_context import _PredefinedToolingContext


class TestPredefinedToolingContext:
    def test_exceptions_starts_empty(self):
        ctx = _PredefinedToolingContext()
        assert ctx.exceptions == []

    def test_append_exception_records(self):
        ctx = _PredefinedToolingContext()
        exc = ConfigResolutionException(message="boom", template_name="dial_rag")
        ctx.append_exception(exc)
        assert ctx.exceptions == [exc]

    def test_append_multiple_preserves_order(self):
        ctx = _PredefinedToolingContext()
        first = ConfigResolutionException(message="a", template_name="x")
        second = ConfigResolutionException(message="b", template_name="y")
        ctx.append_exception(first)
        ctx.append_exception(second)
        assert ctx.exceptions == [first, second]
