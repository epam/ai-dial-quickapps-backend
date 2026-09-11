from fastapi_injector import request_scope
from injector import Binder, Module

from quickapp.shared.deferred_tools._deferred_tools_context import DeferredToolsContext


class DeferredToolsModule(Module):
    """DI binding for the shared deferred-tools catalog.

    Request-scoped holder shared between the REST API, MCP and core agent modules
    so toolsets withheld from the initial LLM payload can be registered and later
    surfaced via the tool_search meta-tool.
    """

    def configure(self, binder: Binder) -> None:
        binder.bind(DeferredToolsContext, to=DeferredToolsContext, scope=request_scope)
