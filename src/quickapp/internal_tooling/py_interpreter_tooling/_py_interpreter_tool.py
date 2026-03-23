from typing import Any

from aidial_sdk.chat_completion import Attachment, Message, Role
from injector import AssistedBuilder, inject

from quickapp.common import DIAL_API_KEY, CompletionResult, StagedBaseTool
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.dial_settings import DialSettings
from quickapp.common.media_types import MediaTypes
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
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


@inject
class _PyInterpreterTool(StagedBaseTool):

    # args_schema: Type[BaseModel] = InterpreterParameters

    # FIXME: mypy warning:
    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_PyInterpreterStageWrapper],
        messages: list[Message],
        client: _PyInterpreterClient,
        py_interpreter_settings: _PyInterpreterSettings,
        session_manager: SessionManager,
        display_content_processor: DisplayContentProcessor,
        dial_settings: DialSettings,
        dial_api_key: DIAL_API_KEY,
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
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
        self.__messages: list[Message] = messages

        self.__client: _PyInterpreterClient = client
        self.__py_interpreter_settings: _PyInterpreterSettings = py_interpreter_settings
        self.__session_manager: SessionManager = session_manager
        self.__display_content_processor: DisplayContentProcessor = display_content_processor
        self.__dial_settings: DialSettings = dial_settings
        self.__dial_api_key: DIAL_API_KEY = dial_api_key
        self.stage_name_component = "Calling Python Code Interpreter"

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> CompletionResult:
        try:
            code: str = kwargs["code"]
            open_session: bool = kwargs.get("open_session", False)
            attachment_urls: list[str] | None = kwargs.get("attachment_urls")
            data_sample_config: DataSampleConfig | None = kwargs.get("data_sample_config")
            display_title: str | None = kwargs.get("display_title")

            async with self.__client as client:
                session_id = (
                    self.__session_manager.get_session_id()
                    or self.__py_interpreter_settings.default_session_id
                )
                session_id = await self.__session_manager.ensure_valid_session(
                    session_id, open_session
                )

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

                result = CompletionResult(
                    content=f"\n```json\n{execution_result.model_dump_json(indent=2)}\n```\n",
                    content_type=MediaTypes.JSON,
                    attachments=attachments,
                )

        except _PyInterpreterError as e:
            result = CompletionResult(
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

        attachments_urls_map = self._get_attachment_urls_map(self.__messages, Role.USER)

        # Transfer each required file that's not already loaded
        for file_name in attachment_urls:
            if file_name in loaded_file_names:
                continue

            for attachment_url, attachment in attachments_urls_map.items():
                sanitized_file_name = file_name.replace(" ", "%20")
                if attachment_url.endswith(file_name) or attachment_url.endswith(
                    sanitized_file_name
                ):
                    url = await InputFileHandler().get_attachment_url(
                        settings=self.__py_interpreter_settings,
                        dial_api_key=self.__dial_api_key,
                        attachment_url=attachment_url,
                        attachment=attachment,
                        dial_url=self.__dial_settings.url,
                    )

                    await client.transfer_input_file(
                        InputFileTransferDto(
                            sessionId=session_id,
                            sourceUrl=url,
                            targetPath=file_name,
                        )
                    )
                    break

    @staticmethod
    def _get_attachment_urls_map(messages: list[Message], role: Role) -> dict[str, Attachment]:
        """Get a map of attachment URLs to Attachment objects"""
        attachments_urls_map: dict[str, Attachment] = {}

        for msg in messages:
            if msg.role == role and msg.custom_content and msg.custom_content.attachments:
                attachments = msg.custom_content.attachments
                for attachment in attachments:
                    if attachment.url:
                        attachments_urls_map[attachment.url] = attachment

        return attachments_urls_map
