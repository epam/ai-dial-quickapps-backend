import logging

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider, provider, singleton

from quickapp.common import DIAL_API_KEY, StagedBaseTool
from quickapp.common.dial_settings import DialSettings
from quickapp.common.tool_names import INTERNAL_CODE_EXECUTION_PYTHON_INTERPRETER_TOOL_NAME
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.predefined import PredefinedTool
from quickapp.config.toolsets.internal import InternalToolSet
from quickapp.shared.config_resolvers.tool_timeout_resolver import ToolTimeoutResolver
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_client import (
    _PyInterpreterClient,
)
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_settings import (
    _PY_INTERPRETER_API_KEY,
    _PyInterpreterSettings,
)
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_tool import _PyInterpreterTool
from quickapp.internal_tooling.py_interpreter_tooling.handlers.content_sanitizer import (
    ContentSanitizer,
)
from quickapp.internal_tooling.py_interpreter_tooling.handlers.input_file_handler import (
    InputFileHandler,
)
from quickapp.internal_tooling.py_interpreter_tooling.handlers.session_manager import SessionManager

logger = logging.getLogger(__name__)


class InternalToolModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(ContentSanitizer, to=ContentSanitizer)
        binder.bind(SessionManager, to=SessionManager, scope=request_scope)
        binder.bind(_PyInterpreterTool, to=_PyInterpreterTool, scope=request_scope)
        binder.bind(InputFileHandler, to=InputFileHandler, scope=request_scope)
        logger.debug("InternalTooling module configuration completed")

    @multiprovider
    def _provide_internal_tools(
        self,
        app_config: ApplicationConfig,
        py_builder: AssistedBuilder[_PyInterpreterTool],
    ) -> list[StagedBaseTool]:
        tools: list[StagedBaseTool] = []

        for tool_set in app_config.tool_sets:
            if isinstance(tool_set, InternalToolSet):
                for tool_config in tool_set.tools:
                    if tool_config.enabled:
                        if isinstance(tool_config, PredefinedTool):
                            logger.warning(
                                "Predefined tool wasn't substituted by real tool. Check application settings."
                            )
                        elif tool_config.open_ai_tool.function.name.startswith(
                            INTERNAL_CODE_EXECUTION_PYTHON_INTERPRETER_TOOL_NAME
                        ):
                            # TODO: remove this filtering by name, the user may configure any name of the tool.
                            tools.append(
                                py_builder.build(
                                    tool_config=tool_config,
                                    name=tool_config.open_ai_tool.function.name,
                                    description=tool_config.open_ai_tool.function.description,
                                )
                            )

        return tools

    @singleton
    @provider
    def _provide_py_interpreter_settings(
        self, dial_settings: DialSettings
    ) -> _PyInterpreterSettings:
        py_interpreter_settings = _PyInterpreterSettings()
        if not py_interpreter_settings.url:
            logger.debug(
                f"No url provided for py_interpreter, using default url {dial_settings.url}"
            )
            py_interpreter_settings.url = dial_settings.url
        if "client_timeout" in py_interpreter_settings.model_fields_set:
            logger.warning(
                "PY_INTERPRETER_CLIENT_TIMEOUT is deprecated and will be removed in a "
                "future release. Use DEFAULT_TOOL_TIMEOUT_SECONDS or "
                "`tool_defaults.timeout_seconds` in app config instead."
            )
        return py_interpreter_settings

    @request_scope
    @provider
    def _provide_api_key(
        self, api_key: DIAL_API_KEY, py_interpreter_settings: _PyInterpreterSettings
    ) -> _PY_INTERPRETER_API_KEY:
        if py_interpreter_settings.local_run:
            if not py_interpreter_settings.api_key:
                raise ValueError("API key for local run with python interpreter is not set.")
            return py_interpreter_settings.api_key
        return api_key

    @request_scope
    @provider
    def _provide_py_interpreter_client(
        self,
        api_key: _PY_INTERPRETER_API_KEY,
        py_interpreter_settings: _PyInterpreterSettings,
        timeout_resolver: ToolTimeoutResolver,
        app_config: ApplicationConfig,
    ) -> _PyInterpreterClient:
        # Legacy PY_INTERPRETER_CLIENT_TIMEOUT shim: wins over DEFAULT_TOOL_TIMEOUT_SECONDS
        # but not over `tool_defaults.timeout_seconds` (which the resolver already honours).
        if (
            app_config.tool_defaults.timeout_seconds is None
            and "client_timeout" in py_interpreter_settings.model_fields_set
        ):
            timeout = py_interpreter_settings.client_timeout
        else:
            timeout = timeout_resolver.resolve()

        return _PyInterpreterClient(
            api_key=api_key,
            base_url=py_interpreter_settings.url,
            timeout=timeout,
            max_retries=py_interpreter_settings.client_max_retries,
        )
