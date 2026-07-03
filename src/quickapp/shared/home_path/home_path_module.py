from fastapi_injector import request_scope
from injector import Binder, Module

from quickapp.shared.home_path.home_path_resolver import HomePathResolver


class HomePathModule(Module):
    """DI binding for the shared agent-home path resolver.

    Request-scoped so the agent home dir is resolved once per request and shared
    between the DIAL-files tools, the path-argument transformer, and the web-fetch
    tool. Previously bound inline in ``DialFilesToolingModule``.
    """

    def configure(self, binder: Binder) -> None:
        binder.bind(HomePathResolver, to=HomePathResolver, scope=request_scope)
