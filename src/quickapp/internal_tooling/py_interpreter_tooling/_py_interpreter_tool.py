import logging
from typing import Any
from urllib.parse import unquote

from aidial_sdk.chat_completion import Attachment, Message
from injector import AssistedBuilder, inject

from quickapp.common import DIAL_API_KEY, StagedBaseTool, ToolCallResult
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.dial_settings import DialSettings
from quickapp.common.media_types import MediaTypes
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.tool_timeout_resolver import ToolTimeoutResolver
from quickapp.common.utils import posix_path_last_segment
from quickapp.config.tools.internal import InternalTool
from quickapp.internal_tooling.py_interpreter_tooling._exceptions import _PyInterpreterError
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_client import (
    _PyInterpreterClient,
)
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_settings import (
    _PyInterpreterSettings,
)
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_stage_wrapper import (
    _PyInterpreterStageWrapper,
)
from quickapp.internal_tooling.py_interpreter_tooling.handlers.content_sanitizer import (
    ContentSanitizer,
)
from quickapp.internal_tooling.py_interpreter_tooling.handlers.display_content_processor import (
    DisplayContentProcessor,
)
from quickapp.internal_tooling.py_interpreter_tooling.handlers.input_file_handler import (
    InputFileHandler,
)
from quickapp.internal_tooling.py_interpreter_tooling.handlers.session_manager import SessionManager
from quickapp.internal_tooling.py_interpreter_tooling.model.args import DataSampleConfig
from quickapp.internal_tooling.py_interpreter_tooling.model.common import PyInterpreterSession
from quickapp.internal_tooling.py_interpreter_tooling.model.request import (
    CodeExecutionRequest,
    InputFileTransferDto,
)
from quickapp.internal_tooling.py_interpreter_tooling.model.response import LoadedFiles

logger = logging.getLogger(__name__)


@inject
class _PyInterpreterTool(StagedBaseTool):

    # args_schema: Type[BaseModel] = InterpreterParameters

    # FIXME: mypy warning:
    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_PyInterpreterStageWrapper],
        messages_mixin: MessagesMixin,
        client: _PyInterpreterClient,
        py_interpreter_settings: _PyInterpreterSettings,
        session_manager: SessionManager,
        display_content_processor: DisplayContentProcessor,
        dial_settings: DialSettings,
        dial_api_key: DIAL_API_KEY,
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        timeout_resolver: ToolTimeoutResolver,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            argument_transformers=argument_transformers,
            **kwargs,
        )
        self.__messages_mixin: MessagesMixin = messages_mixin

        self.__client: _PyInterpreterClient = client
        self.__py_interpreter_settings: _PyInterpreterSettings = py_interpreter_settings
        self.__session_manager: SessionManager = session_manager
        self.__display_content_processor: DisplayContentProcessor = display_content_processor
        self.__dial_settings: DialSettings = dial_settings
        self.__dial_api_key: DIAL_API_KEY = dial_api_key
        self.__timeout_resolver: ToolTimeoutResolver = timeout_resolver
        self.stage_name_component = "Calling Python Code Interpreter"

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        try:
            code: str = kwargs["code"]
            attachment_urls: list[str] | None = kwargs.get("attachment_urls")
            raw_data_sample_config = kwargs.get("data_sample_config")
            data_sample_config: DataSampleConfig | None = (
                DataSampleConfig.model_validate(raw_data_sample_config)
                if raw_data_sample_config is not None
                else None
            )
            display_title: str | None = kwargs.get("display_title")

            async with self.__client as client:
                session_id = (
                    self.__session_manager.get_session_id()
                    or self.__py_interpreter_settings.default_session_id
                )
                session_id = await self.__session_manager.ensure_valid_session(session_id)

                await self._prepare_input_files(
                    client=client,
                    session_id=session_id,
                    attachment_urls=attachment_urls,
                )

                execution_result = await client.execute_code(
                    CodeExecutionRequest(sessionId=session_id, code=code)
                )

                execution_result = ContentSanitizer.sanitize(
                    data=execution_result, data_sample_config=data_sample_config
                )

                attachments = []
                if execution_result.display:
                    attachments = await self.__display_content_processor.process_display_content(
                        execution_result.display, display_title=display_title
                    )
                    execution_result = self.__display_content_processor.sanitize_display_content(
                        execution_result
                    )

                result = ToolCallResult(
                    content=f"\n```json\n{execution_result.model_dump_json(indent=2)}\n```\n",
                    content_type=MediaTypes.JSON,
                    attachments=attachments,
                )

        except _PyInterpreterError as e:
            result = ToolCallResult(
                content=str(e),
                content_type=MediaTypes.JSON,
                attachments=None,
            )

        if stage_wrapper:
            stage_wrapper.add_result(result)

        return result

    async def _prepare_input_files(
        self,
        client: _PyInterpreterClient,
        session_id: str,
        attachment_urls: list[str] | None = None,
    ) -> None:
        """Prepare input files for the code execution"""
        if not attachment_urls:
            return

        # Get already loaded files
        loaded_files: LoadedFiles = await client.list_files(
            PyInterpreterSession(sessionId=session_id)
        )
        loaded_file_names = [file.path for file in loaded_files.files]

        attachments_urls_map = self._get_attachment_urls_map(self.__messages_mixin.messages)

        errors: list[str] = []

        # Transfer each required file that's not already loaded
        for file_name in attachment_urls:
            target_path = unquote(posix_path_last_segment(file_name))

            if target_path in loaded_file_names:
                continue

            matched = False
            for attachment_url, attachment in attachments_urls_map.items():
                sanitized_file_name = file_name.replace(" ", "%20")
                if attachment_url.endswith(file_name) or attachment_url.endswith(
                    sanitized_file_name
                ):
                    matched = True
                    try:
                        url = await InputFileHandler().get_attachment_url(
                            settings=self.__py_interpreter_settings,
                            dial_api_key=self.__dial_api_key,
                            attachment_url=attachment_url,
                            attachment=attachment,
                            dial_url=self.__dial_settings.url,
                            timeout=self.__timeout_resolver.resolve(),
                        )

                        await client.transfer_input_file(
                            InputFileTransferDto(
                                sessionId=session_id,
                                sourceUrl=url,
                                targetPath=target_path,
                            )
                        )
                    except Exception as e:
                        logger.warning("Failed to transfer file %s: %s", target_path, e)
                        errors.append(f"{target_path}: {e}")
                    break

            if not matched:
                logger.warning("No matching attachment found for: %s", file_name)
                errors.append(
                    f"{unquote(posix_path_last_segment(file_name))}: "
                    f"no matching attachment found in conversation"
                )

        if errors:
            raise _PyInterpreterError(
                "Failed to prepare input files:\n" + "\n".join(f"- {e}" for e in errors)
            )

    @staticmethod
    def _get_attachment_urls_map(messages: list[Message]) -> dict[str, Attachment]:
        """Get a map of attachment URLs to Attachment objects from all messages."""
        attachments_urls_map: dict[str, Attachment] = {}

        for msg in messages:
            if msg.custom_content and msg.custom_content.attachments:
                for attachment in msg.custom_content.attachments:
                    if attachment.url:
                        attachments_urls_map[attachment.url] = attachment

        return attachments_urls_map
