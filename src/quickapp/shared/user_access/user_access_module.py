from fastapi_injector import request_scope
from injector import Binder, Module

from .tool_access_filter import ToolAccessFilter


class UserAccessModule(Module):
    """DI bindings for per-user tool access filtering (opt-in per app)."""

    def configure(self, binder: Binder) -> None:
        binder.bind(ToolAccessFilter, to=ToolAccessFilter, scope=request_scope)
