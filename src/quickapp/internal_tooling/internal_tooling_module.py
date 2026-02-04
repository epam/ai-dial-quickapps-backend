import logging

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider, provider, singleton

from quickapp.common import DIAL_API_KEY, StagedBaseTool
from quickapp.common.dial_settings import DialSettings
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.predefined import PredefinedTool
from quickapp.config.toolsets.internal import InternalToolSet
from quickapp.internal_tooling.attachment_notification_tooling._available_context_tool import (
    _AvailableContextTool,
)
from quickapp.internal_tooling.attachment_notification_tooling._tool_configs import (
    AVAILABLE_CONTEXT_TOOL_CONFIG,
    should_activate_context_tool,
)
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
from quickapp.internal_tooling.py_interpreter_tooling.handlers.session_manager import SessionManager
from quickapp.internal_tooling.skill_reader_tooling._skill_reader_tool import _SkillReaderTool
from quickapp.internal_tooling.skill_reader_tooling._tool_configs import (
    SKILL_READER_TOOL_CONFIG,
    SKILL_READER_TOOL_NAME,
)

logger = logging.getLogger(__name__)


class InternalToolModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(ContentSanitizer, to=ContentSanitizer)
        binder.bind(SessionManager, to=SessionManager, scope=request_scope)
        binder.bind(_PyInterpreterTool, to=_PyInterpreterTool, scope=request_scope)
        binder.bind(_AvailableContextTool, to=_AvailableContextTool, scope=request_scope)
        binder.bind(_SkillReaderTool, to=_SkillReaderTool, scope=request_scope)

        logger.debug("InternalTooling module configuration completed")

    @multiprovider
    def _provide_internal_tools(
        self,
        app_config: ApplicationConfig,
        messages_context: MessagesMixin,
        py_builder: AssistedBuilder[_PyInterpreterTool],
        ac_builder: AssistedBuilder[_AvailableContextTool],
        skill_reader_builder: AssistedBuilder[_SkillReaderTool],
    ) -> list[StagedBaseTool]:
        tools: list[StagedBaseTool] = []

        # Add skill reader tool (always enabled)
        tools.append(
            skill_reader_builder.build(
                tool_config=SKILL_READER_TOOL_CONFIG,
                name=SKILL_READER_TOOL_NAME,
                description=SKILL_READER_TOOL_CONFIG.open_ai_tool.function.description,
            )
        )

        for tool_set in app_config.tool_sets:
            if isinstance(tool_set, InternalToolSet):
                for tool_config in tool_set.tools:
                    if tool_config.enabled:
                        if isinstance(tool_config, PredefinedTool):
                            logger.warning(
                                "Predefined tool wasn't substituted by real tool. Check application settings."
                            )
                        elif tool_config.open_ai_tool.function.name.startswith(
                            'python_code_interpreter'
                        ):
                            # TODO: remove this filtering by name, the user may configure any name of the tool.
                            tools.append(
                                py_builder.build(
                                    tool_config=tool_config,
                                    name=tool_config.open_ai_tool.function.name,
                                    description=tool_config.open_ai_tool.function.description,
                                )
                            )


        if should_activate_context_tool(app_config.contexts, messages_context.messages):
            tools.append(
                ac_builder.build(
                    tool_config=AVAILABLE_CONTEXT_TOOL_CONFIG,
                    name=AVAILABLE_CONTEXT_TOOL_CONFIG.open_ai_tool.function.name,
                    description=AVAILABLE_CONTEXT_TOOL_CONFIG.open_ai_tool.function.description,
                    contexts=list(app_config.contexts),
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
        self, api_key: _PY_INTERPRETER_API_KEY, py_interpreter_settings: _PyInterpreterSettings
    ) -> _PyInterpreterClient:
        return _PyInterpreterClient(
            api_key=api_key,
            base_url=py_interpreter_settings.url,
            timeout=py_interpreter_settings.client_timeout,
            max_retries=py_interpreter_settings.client_max_retries,
        )
