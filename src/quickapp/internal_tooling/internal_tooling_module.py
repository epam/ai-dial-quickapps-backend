import logging
import os

from aidial_sdk.chat_completion import Message
from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider, provider, singleton

from quickapp.common import DIAL_API_KEY, StagedBaseTool
from quickapp.common.base_transformer import MessagesTransformer
from quickapp.common.dial_settings import DialSettings
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.predefined import PredefinedTool
from quickapp.config.toolsets.internal import InternalToolSet
from quickapp.internal_tooling.attachment_notification_tooling._available_context_tool import (
    _AvailableContextTool,
)
from quickapp.internal_tooling.attachment_notification_tooling._attachment_notification_injector import (
    AttachmentNotificationInjector,
)
from quickapp.internal_tooling.attachment_notification_tooling._context_entries import (
    should_activate_context_tool,
)
from quickapp.internal_tooling.attachment_notification_tooling._tool_configs import (
    AVAILABLE_CONTEXT_TOOL_CONFIG,
)
from quickapp.internal_tooling.content_download_tooling._content_download_tool import (
    _ContentDownloadTool,
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

logger = logging.getLogger(__name__)


class InternalToolModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(ContentSanitizer, to=ContentSanitizer)
        binder.bind(SessionManager, to=SessionManager, scope=request_scope)
        binder.bind(_PyInterpreterTool, to=_PyInterpreterTool, scope=request_scope)
        binder.bind(_ContentDownloadTool, to=_ContentDownloadTool, scope=request_scope)
        binder.bind(_AvailableContextTool, to=_AvailableContextTool, scope=request_scope)
        binder.bind(
            AttachmentNotificationInjector,
            to=AttachmentNotificationInjector,
            scope=request_scope,
        )

        logger.debug("InternalTooling module configuration completed")

    @multiprovider
    def _provide_attachment_notification_transformer(
        self,
        notification_injector: AttachmentNotificationInjector,
    ) -> list[MessagesTransformer]:
        return [notification_injector]

    @multiprovider
    def _provide_internal_tools(
        self,
        app_config: ApplicationConfig,
        messages: list[Message],
        py_builder: AssistedBuilder[_PyInterpreterTool],
        cd_builder: AssistedBuilder[_ContentDownloadTool],
        ac_builder: AssistedBuilder[_AvailableContextTool],
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
                        elif tool_config.open_ai_tool.function.name.startswith(
                            'content_downloader'
                        ):
                            tools.append(
                                cd_builder.build(
                                    tool_config=tool_config,
                                    name=tool_config.open_ai_tool.function.name,
                                    description=tool_config.open_ai_tool.function.description,
                                    content_size_limit=int(
                                        os.getenv("CONTENT_DOWNLOADER_FILE_SIZE_LIMIT", "20971520")
                                    ),  # 20Mb
                                )
                            )

        if should_activate_context_tool(app_config.contexts, messages):
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
