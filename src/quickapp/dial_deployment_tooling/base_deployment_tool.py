import json
import logging
from typing import Any, Optional, cast

from aidial_client.types.chat.request_param import (
    AssistantMessageParam,
    AttachmentParam,
    CustomContentParam,
    UserMessageParam,
)
from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.chat_completion.request import Attachment as SdkAttachment
from injector import AssistedBuilder

from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.utils import to_plain_dict
from quickapp.config.tools.deployment import ContentPropagation, DialDeploymentTool
from quickapp.dial_deployment_tooling.constants import ATTACHMENT_PARAM, CONTENT_PARAM
from quickapp.dial_deployment_tooling.dial_completion_service import DialCompletionService

from .deployment_stage_wrapper import DeploymentStageWrapper
from quickapp.dial_core_services.dial_file_service import DialFileService

logger = logging.getLogger(__name__)


class BaseDeploymentTool(StagedBaseTool):

    def __init__(
        self,
        application_id: str,
        application_name: str,
        tool_config: DialDeploymentTool,
        content_propagation: Optional[ContentPropagation],
        dial_completion_service: DialCompletionService,
        messages: list[Message],
        perf_timer: PerformanceTimer,
        stage_wrapper_builder: AssistedBuilder[DeploymentStageWrapper],
        file_service: DialFileService,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            file_service=file_service,
            **kwargs,
        )
        self.__application_id: str = application_id
        self.__application_name: str = application_name
        self.__dial_completion_service: DialCompletionService = dial_completion_service
        self.__content_propagation: Optional[ContentPropagation] = content_propagation
        self.__messages: list[Message] = messages

    async def _run_in_stage_async(
        self,
        stage_wrapper: Optional[BaseStageWrapper],
        attachment_urls: Optional[list[str]] = None,
        **kwargs,
    ) -> CompletionResult:
        tool_config = cast(DialDeploymentTool, self.tool_config)
        history = None
        if self.__content_propagation and self.__content_propagation.propagate_history:
            history = await self._extract_tool_history(tool_config.open_ai_tool.function.name)
        return await self.__dial_completion_service.complete_request_async(
            kwargs,
            self.__application_id,
            self.__application_name,
            stage_wrapper,
            attachment_urls,
            history=history,
        )

    @staticmethod
    def _sdk_attachment_to_param(attachment: SdkAttachment) -> AttachmentParam:
        return AttachmentParam(
            **attachment.model_dump(  # type: ignore[typeddict-item]
                include=set(AttachmentParam.__annotations__),
                exclude_none=True,
            )
        )

    async def _extract_tool_history(
        self,
        tool_name: str,
    ) -> list[UserMessageParam | AssistantMessageParam]:
        if not tool_name:
            return []

        # Build map: tool_call_id -> (content, custom_content)
        tool_result_by_id: dict[str, tuple[str, Any]] = {}
        for msg in self.__messages:
            if msg.role == Role.TOOL and msg.tool_call_id and msg.content:
                content = str(msg.content) if not isinstance(msg.content, str) else msg.content
                tool_result_by_id[msg.tool_call_id] = (content, msg.custom_content)

        # Walk ASSISTANT messages, find completed tool_calls matching tool_name
        history: list[UserMessageParam | AssistantMessageParam] = []
        for msg in self.__messages:
            if msg.role != Role.ASSISTANT or not msg.tool_calls:
                continue

            for tc in msg.tool_calls:
                if tc.function.name != tool_name:
                    continue

                result_entry = tool_result_by_id.get(tc.id)
                if result_entry is None:
                    # Current call — its TOOL result hasn't been appended yet
                    continue

                tool_content, tool_custom_content = result_entry

                user_msg = await self._build_user_message_from_tool_call(tc.function.arguments)
                if user_msg is not None:
                    history.append(user_msg)

                if tool_content:
                    assistant_msg = self._build_assistant_message(tool_content, tool_custom_content)
                    history.append(assistant_msg)

        return history

    async def _build_user_message_from_tool_call(
        self, raw_arguments: str
    ) -> UserMessageParam | None:
        try:
            args = json.loads(raw_arguments)
            query: str = args.get(CONTENT_PARAM, "")
            attachment_urls: list[str] | None = args.get(ATTACHMENT_PARAM)
        except (json.JSONDecodeError, AttributeError):
            return None

        if not query and not attachment_urls:
            return None

        user_msg = UserMessageParam(role="user", content=query or "")
        if attachment_urls:
            resolved = await self.__dial_completion_service.resolve_attachment_urls(attachment_urls)
            if resolved:
                user_msg["custom_content"] = CustomContentParam(attachments=resolved)
        return user_msg

    @classmethod
    def _build_assistant_message(cls, content: str, custom_content: Any) -> AssistantMessageParam:
        assistant_msg = AssistantMessageParam(role="assistant", content=content)

        if custom_content:
            cc_param = CustomContentParam()
            if custom_content.attachments:
                cc_param["attachments"] = [
                    cls._sdk_attachment_to_param(a) for a in custom_content.attachments
                ]
            if custom_content.state is not None:
                cc_param["state"] = custom_content.state
            if cc_param:
                assistant_msg["custom_content"] = cc_param

        return assistant_msg

    async def _pre_process_params(self, **kwargs: Any) -> Any:

        pre_processed = await super()._pre_process_params(**kwargs)
        prepared: dict[str, Any] = {}

        # If tool config defines defaults, normalize them first
        if isinstance(self.tool_config, DialDeploymentTool):
            tool_config = cast(DialDeploymentTool, self.tool_config)
            params = tool_config.deployment.parameters
            self._merge_to_prepared_params(params, prepared)

        # Now process runtime kwargs - these should override defaults
        prepared.update(pre_processed)

        logger.debug(f"Pre-processed tool parameters: {prepared}")

        return prepared

    @staticmethod
    def _merge_to_prepared_params(params: Any, prepared: dict[str, Any]):
        """Merge deployment parameters into a plain dict. Grouping into extra_body is done in DialCompletionService."""
        params_dict = to_plain_dict(params)
        if isinstance(params_dict, dict):
            for key, value in params_dict.items():
                if value is None or value == {}:
                    continue
                prepared[key] = value
