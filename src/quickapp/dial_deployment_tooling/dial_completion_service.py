import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Tuple

from aidial_client import AsyncDial
from aidial_client.resources import AsyncMetadata
from aidial_client.types.chat.request_param import (
    AssistantMessageParam,
    AttachmentParam,
    CustomContentParam,
    UserMessageParam,
)
from aidial_client.types.chat.response import Attachment, CompletionUsage
from injector import inject

from quickapp.common import CompletionResult
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.deployment_usage import DeploymentUsage
from quickapp.common.utils import to_plain_dict
from quickapp.dial_deployment_tooling.constants import (
    ATTACHMENT_PARAM,
    CONFIGURATION,
    CONTENT_PARAM,
    CUSTOM_CONTENT,
    EXTRA_BODY,
)

logger = logging.getLogger(__name__)


@dataclass
class _StreamResult:
    content: str = ""
    attachments: list[Any] | None = None
    state: Any = None
    usage: CompletionUsage | None = None
    statistics: dict[str, Any] = field(default_factory=dict)

    def extend_attachments(self, attachments: list[Any]) -> None:
        if self.attachments is None:
            self.attachments = []
        self.attachments.extend(attachments)


@inject
class DialCompletionService:

    def __init__(self, dial_client: AsyncDial):
        self.__dial_client: AsyncDial = dial_client

    @staticmethod
    def _prepare_custom_fields(items: Iterable[Tuple[str, Any]]) -> Dict[str, Any] | None:
        # kept for backward compatibility in rare cases
        normalized: dict[str, Any] = {}
        for k, v in items:
            if k == CONTENT_PARAM or k == ATTACHMENT_PARAM:
                continue
            n = to_plain_dict(v)
            if n == {}:
                continue
            normalized[k] = n
        if normalized:
            return {CONFIGURATION: normalized}
        return None

    async def complete_request_async(
        self,
        params: Dict[str, Any],
        deployment_id: str,
        deployment_name: str,
        stage_wrapper: BaseStageWrapper | None,
        relative_attachment_urls: list[str] | None = None,
        history: list[UserMessageParam | AssistantMessageParam] | None = None,
    ) -> CompletionResult:
        # Expect params to be pre-processed by BaseDeploymentTool._pre_process_params
        content = params.get(CONTENT_PARAM, "")
        if not content:
            logger.warning(
                "Tool call content is empty. Check the tool configuration,"
                " it should use `query` parameter"
            )

        messages = await self.__build_request_messages(content, relative_attachment_urls, history)
        chat_params = self._build_chat_completion_params(params, deployment_id, messages)
        chunks = await self.__dial_client.chat.completions.create(**chat_params)
        result = await self._consume_stream(chunks, stage_wrapper)

        return CompletionResult(
            content=result.content,
            content_type="text/markdown",
            attachments=result.attachments,
            state=result.state,
            usage=self.__get_deployment_usage(
                result.usage, result.statistics, deployment_id, deployment_name
            ),
        )

    @staticmethod
    def _build_chat_completion_params(
        params: Dict[str, Any],
        deployment_id: str,
        messages: list[UserMessageParam | AssistantMessageParam],
    ) -> dict[str, Any]:
        chat_completion_params: dict[str, Any] = {
            "deployment_name": deployment_id,
            "stream": True,
            "messages": messages,
        }

        # query and attachment_urls are used only for messages; all other params go in extra_body
        extra_body: dict[str, Any] = dict(params.get(EXTRA_BODY) or {})
        for k, v in params.items():
            if k in (CONTENT_PARAM, ATTACHMENT_PARAM, EXTRA_BODY):
                continue
            if v is None or v == {}:
                continue
            extra_body[k] = v
        if extra_body:
            chat_completion_params[EXTRA_BODY] = extra_body

        return chat_completion_params

    @staticmethod
    def _fix_attachment(attachment: Any) -> None:
        """Bugfix issue#16: if attachment has no data and no url, use reference_url as url."""
        if attachment.data is None and attachment.url is None:
            if attachment.reference_url is None:
                attachment["data"] = ""
            else:
                attachment.url = attachment.reference_url

    @staticmethod
    def _to_client_attachment(attachment: Any) -> Attachment:
        return Attachment(
            type=attachment.type,
            title=attachment.title,
            data=attachment.data,
            url=attachment.url,
            reference_url=attachment.reference_url,
            reference_type=attachment.reference_type,
        )

    async def _consume_stream(
        self,
        chunks: Any,
        stage_wrapper: BaseStageWrapper | None,
    ) -> _StreamResult:
        result = _StreamResult()
        content_parts: list[str] = []

        if stage_wrapper:
            stage_wrapper.append_stage_content("> #### Response:\n")

        async for chunk in chunks:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            if delta:
                if delta.content:
                    if stage_wrapper:
                        stage_wrapper.append_stage_content(delta.content)
                    content_parts.append(delta.content)

                if delta.custom_content and delta.custom_content.attachments:
                    attachments = delta.custom_content.attachments
                    result.extend_attachments(attachments)
                    if stage_wrapper:
                        for attachment in attachments:
                            self._fix_attachment(attachment)
                            stage_wrapper.add_stage_attachment(
                                self._to_client_attachment(attachment)
                            )
                elif delta.custom_content and delta.custom_content.state:
                    result.state = delta.custom_content.state

            if chunk.usage:
                result.usage = chunk.usage
            result.statistics = chunk.model_extra.get("statistics", {}).get("usage_per_model", {})

        result.content = "".join(content_parts)
        return result

    @staticmethod
    def __get_deployment_usage(
        usage: CompletionUsage | None,
        statistics: dict | None,
        deployment_id: str,
        deployment_name: str,
    ) -> List[DeploymentUsage] | None:
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
        relative_attachment_urls: list[str] | None = None,
        history: list[UserMessageParam | AssistantMessageParam] | None = None,
    ) -> list[UserMessageParam | AssistantMessageParam]:
        messages: list[UserMessageParam | AssistantMessageParam] = []
        if history:
            messages.extend(history)
        messages.append(
            await self.__user_message_from_content_and_attachments(
                content, relative_attachment_urls
            )
        )
        return messages

    async def __user_message_from_content_and_attachments(
        self, content, relative_attachment_urls: list[str] | None = None
    ) -> UserMessageParam:
        message = UserMessageParam(role="user", content=content)
        attachments = await self.resolve_attachment_urls(relative_attachment_urls)
        if attachments and len(attachments) > 0:
            message[CUSTOM_CONTENT] = CustomContentParam(attachments=attachments)
        return message

    async def resolve_attachment_urls(
        self, relative_attachment_urls: list[str] | None
    ) -> list[AttachmentParam]:
        return [await self._resolve_attachment(url) for url in (relative_attachment_urls or [])]

    async def _resolve_attachment(self, file_relative_url: str) -> AttachmentParam:
        metadata: AsyncMetadata = self.__dial_client.metadata
        fileinfo = await metadata.get("files", file_relative_url)
        return AttachmentParam(
            type=fileinfo.content_type,
            title=fileinfo.name,
            url=fileinfo.url,
        )
