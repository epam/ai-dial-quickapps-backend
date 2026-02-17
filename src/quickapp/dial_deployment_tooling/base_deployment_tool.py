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
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
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
        param = AttachmentParam()
        if attachment.type is not None:
            param["type"] = attachment.type
        if attachment.title is not None:
            param["title"] = attachment.title
        if attachment.data is not None:
            param["data"] = attachment.data
        if attachment.url is not None:
            param["url"] = attachment.url
        if attachment.reference_url is not None:
            param["reference_url"] = attachment.reference_url
        if attachment.reference_type is not None:
            param["reference_type"] = attachment.reference_type
        return param

    async def _extract_tool_history(
        self,
        tool_name: str,
    ) -> list[UserMessageParam | AssistantMessageParam]:
        if not tool_name:
            return []

        messages = self.__messages

        # Build map: tool_call_id -> (content, custom_content)
        tool_result_by_id: dict[str, tuple[str, Any]] = {}
        for msg in messages:
            if msg.role == Role.TOOL and msg.tool_call_id and msg.content:
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                tool_result_by_id[msg.tool_call_id] = (content, msg.custom_content)

        # Walk ASSISTANT messages, find tool_calls matching tool_name
        history: list[UserMessageParam | AssistantMessageParam] = []
        for msg in messages:
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

                # --- Request side: build UserMessageParam ---
                try:
                    args = json.loads(tc.function.arguments)
                    query = args.get(CONTENT_PARAM, "")
                    attachment_urls: list[str] | None = args.get(ATTACHMENT_PARAM)
                except (json.JSONDecodeError, AttributeError):
                    query = ""
                    attachment_urls = None

                if query or attachment_urls:
                    user_msg = UserMessageParam(role="user", content=query or "")
                    if attachment_urls:
                        resolved = await self.__dial_completion_service.resolve_attachment_urls(
                            attachment_urls
                        )
                        if resolved:
                            user_msg["custom_content"] = CustomContentParam(attachments=resolved)
                    history.append(user_msg)

                # --- Response side: build AssistantMessageParam ---
                if tool_content:
                    assistant_msg = AssistantMessageParam(role="assistant", content=tool_content)

                    if tool_custom_content:
                        cc_param = CustomContentParam()
                        if tool_custom_content.attachments:
                            cc_param["attachments"] = [
                                self._sdk_attachment_to_param(a)
                                for a in tool_custom_content.attachments
                            ]
                        if tool_custom_content.state is not None:
                            cc_param["state"] = tool_custom_content.state
                        if cc_param:
                            assistant_msg["custom_content"] = cc_param

                    history.append(assistant_msg)

        return history

    def _pre_process_params(self, **kwargs: Any) -> Any:

        prepared: dict[str, Any] = {}

        # If tool config defines defaults, normalize them first
        if isinstance(self.tool_config, DialDeploymentTool):
            tool_config = cast(DialDeploymentTool, self.tool_config)
            params = tool_config.deployment.parameters
            self.merge_to_prepared_params(params, prepared)

        # Now process runtime kwargs - these should override defaults
        prepared.update(kwargs)

        logger.debug(f"Pre-processed tool parameters: {prepared}")

        return prepared

    def merge_to_prepared_params(self, params: Any, prepared: dict[str, Any]):
        """Merge deployment parameters into a plain dict. Grouping into extra_body is done in DialCompletionService."""
        params_dict = to_plain_dict(params)
        if isinstance(params_dict, dict):
            for key, value in params_dict.items():
                if value is None or value == {}:
                    continue
                prepared[key] = value
