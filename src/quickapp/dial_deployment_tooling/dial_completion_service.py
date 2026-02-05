import logging
from typing import Any, Dict, List, Optional, Iterable, Tuple

from aidial_client import AsyncDial
from aidial_client.resources import AsyncMetadata
from aidial_client.types.chat.request_param import (
    AssistantMessageParam,
    AttachmentParam,
    CustomContentParam,
    UserMessageParam,
)
from aidial_client.types.chat.response import Attachment, ChatCompletionResponse, CompletionUsage
from aidial_sdk.chat_completion import CustomContent, Message, Role
from injector import inject

from quickapp.common import CompletionResult
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.deployment_usage import DeploymentUsage
from quickapp.config.tools.deployment import ContentPropagation
from quickapp.common.utils import to_plain_dict

_CONTENT_PARAM: str = "query"
_ATTACHMENT_PARAM: str = "attachment_urls"
_EXTRA_BODY: str = "extra_body"
_CUSTOM_FIELDS: str = "custom_fields"

logger = logging.getLogger(__name__)


@inject
class DialCompletionService:

    def __init__(self, dial_client: AsyncDial, messages: list[Message]):
        self.__dial_client: AsyncDial = dial_client
        self.__history: list[Message] = messages[:-1] if messages and len(messages) > 0 else []

    @staticmethod
    def _prepare_custom_fields(items: Iterable[Tuple[str, Any]]) -> Optional[Dict[str, Any]]:
        normalized: dict[str, Any] = {}
        for k, v in items:
            if k == _CONTENT_PARAM or k == _ATTACHMENT_PARAM:
                continue
            n = to_plain_dict(v)
            if n == {}:
                continue
            normalized[k] = n
        if normalized:
            return {"configuration": normalized}
        return None

    async def complete_request_async(
        self,
        params: Dict[str, Any],
        deployment_id: str,
        deployment_name: str,
        content_propagation: Optional[ContentPropagation],
        stage_wrapper: Optional[BaseStageWrapper],
        relative_attachment_urls: Optional[list[str]] = None,
    ) -> CompletionResult:
        content = params.get(_CONTENT_PARAM, "")
        if not content:
            logger.warning(
                "Tool call content is empty. Check the tool configuration, it should use `query` parameter"
            )
        messages = await self.__build_request_messages(
            content, content_propagation, relative_attachment_urls
        )
        chat_completion_params: dict[str, Any] = {
            "deployment_name": deployment_id,
            "stream": True,
            "messages": messages,
        }

        custom_fields = self._prepare_custom_fields(params.items())
        if custom_fields:
            chat_completion_params[_EXTRA_BODY] = {_CUSTOM_FIELDS: custom_fields}


        chunks = await self.__dial_client.chat.completions.create(**chat_completion_params)

        content_parts = []
        custom_content: CustomContent = CustomContent(attachments=[])
        usage: Optional[CompletionUsage] = None
        statistics: dict[str, Any] = {}

        if stage_wrapper:
            stage_wrapper.append_stage_content("> #### Response:\n")
        async for chunk in chunks:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if delta:
                    if delta.content:
                        if stage_wrapper:
                            stage_wrapper.append_stage_content(delta.content)
                        content_parts.append(delta.content)
                    if delta.custom_content and delta.custom_content.attachments:
                        attachments = delta.custom_content.attachments
                        custom_content.attachments.extend(attachments)
                        if stage_wrapper:
                            for attachment in attachments:
                                # bugfix issue#16 - if attachment has no data and no url, but has reference_url, use it as url
                                if attachment.data is None and attachment.url is None:
                                    if attachment.reference_url is None:
                                        attachment['data'] = ''
                                    else:
                                        attachment.url = attachment.reference_url
                                stage_wrapper.add_stage_attachment(
                                    Attachment(
                                        type=attachment.type,
                                        title=attachment.title,
                                        data=attachment.data,
                                        url=attachment.url,
                                        reference_url=attachment.reference_url,
                                        reference_type=attachment.reference_type,
                                    )
                                )
                if chunk.usage:
                    usage = chunk.usage
                statistics = chunk.model_extra.get("statistics", {}).get("usage_per_model", {})

        return CompletionResult(
            content="".join(content_parts),
            content_type="text/markdown",
            attachments=custom_content.attachments,
            usage=self.__get_deployment_usage(usage, statistics, deployment_id, deployment_name),
        )

    @staticmethod
    def __get_deployment_usage(
        usage: Optional[CompletionUsage],
        statistics: Optional[dict],
        deployment_id: str,
        deployment_name: str,
    ) -> Optional[List[DeploymentUsage]]:
        if statistics:
            result = []
            for model_usage in statistics:
                result.append(
                    DeploymentUsage(
                        model_name=model_usage.get("model"),
                        deployment_name=deployment_name,
                        deployment_id=deployment_id,
                        prompt_tokens=model_usage.get("prompt_tokens") or 0,
                        completion_tokens=model_usage.get("completion_tokens") or 0,
                    )
                )
            return result
        elif usage:
            return [
                DeploymentUsage(
                    model_name=deployment_id,
                    deployment_name=deployment_name,
                    deployment_id=deployment_id,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                )
            ]

        return None

    async def __build_request_messages(
        self,
        content: str,
        content_propagation: Optional[ContentPropagation],
        relative_attachment_urls: Optional[list[str]] = None,
    ) -> list[UserMessageParam | AssistantMessageParam]:
        messages: list[UserMessageParam | AssistantMessageParam] = []
        if content_propagation and content_propagation.propagate_history:
            messages.extend(self.__build_message_params_from_history())
        messages.append(
            await self.__user_message_from_content_and_attachments(
                content, relative_attachment_urls
            )
        )
        return messages

    def __build_message_params_from_history(
        self,
    ) -> list[UserMessageParam | AssistantMessageParam]:
        return [
            (
                UserMessageParam(role="user", content=message.content)
                if message.role == Role.USER
                else AssistantMessageParam(role="assistant", content=message.content)
            )
            for message in self.__history
            if message.content
        ]

    @staticmethod
    def __get_attachments_from_response(
        response: ChatCompletionResponse,
    ) -> Optional[list[Attachment]]:
        custom_content = response.choices[0].message.custom_content
        return custom_content.attachments if custom_content and custom_content.attachments else None

    async def __user_message_from_content_and_attachments(
        self, content, relative_attachment_urls: Optional[list[str]] = None
    ) -> UserMessageParam:
        message = UserMessageParam(role="user", content=content)
        attachments = await self.__attachment_params_from_urls(relative_attachment_urls)
        if attachments and len(attachments) > 0:
            message["custom_content"] = CustomContentParam(attachments=attachments)
        return message

    async def __attachment_params_from_urls(
        self, relative_attachment_urls: Optional[list[str]]
    ) -> list[AttachmentParam]:
        return [await self.__attachment_param(url) for url in (relative_attachment_urls or [])]

    async def __attachment_param(self, file_relative_url: str) -> AttachmentParam:
        metadata: AsyncMetadata = self.__dial_client.metadata
        fileinfo = await metadata.get("files", file_relative_url)
        return AttachmentParam(
            type=fileinfo.content_type,
            title=fileinfo.name,
            url=fileinfo.url,
        )

    def _build_result_message(self, content, attachments, deployment_usage):
        m = Message(
            role=Role.TOOL,
            content=content,
            custom_content=CustomContent(
                attachments=attachments, state={"usage": deployment_usage}
            ),
        )
        return m
