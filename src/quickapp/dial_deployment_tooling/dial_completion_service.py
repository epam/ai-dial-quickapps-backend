import logging
from collections.abc import AsyncIterable, Iterable
from functools import partial
from typing import Any

from aidial_client.types.chat import response as dial_client_models
from aidial_client.types.chat.request_param import (
    AssistantMessageParam,
    AttachmentParam,
    CustomContentParam,
    UserMessageParam,
)
from aidial_sdk import chat_completion as dial_sdk_models
from injector import inject
from openai import AsyncAzureOpenAI
from openai.types.chat import ChatCompletionChunk
from pydantic import BaseModel, Field

from quickapp.common import CompletionResult, ForwardedHeaders
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.chat_completion_stream import (
    ChatStreamEvent,
    ChatStreamFootprintMode,
    ChunkUsageFootprint,
    NormalizedChoiceDelta,
    consume_chat_completion_chunks,
    parse_chat_completion_chunk,
)
from quickapp.common.deployment_usage import DeploymentUsage
from quickapp.common.dial_core_client import DialCoreClient
from quickapp.common.utils import to_plain_dict
from quickapp.dial_deployment_tooling.constants import (
    ATTACHMENT_PARAM,
    CONFIGURATION,
    CONTENT_PARAM,
    EXTRA_BODY,
    EXTRA_HEADERS,
)

logger = logging.getLogger(__name__)


def _to_sdk_attachment(attachment: dial_client_models.Attachment) -> dial_sdk_models.Attachment:
    return dial_sdk_models.Attachment(**attachment.model_dump())


class _StreamResult(BaseModel):
    content: str = ""
    attachments: list[dial_sdk_models.Attachment] | None = None
    state: dict[str, Any] | None = None
    usage: Any = None
    statistics: dict[str, Any] = Field(default_factory=dict)

    def extend_attachments(self, attachments: list[Any]) -> None:
        if self.attachments is None:
            self.attachments = []
        self.attachments.extend(_to_sdk_attachment(a) for a in attachments)


@inject
class DialCompletionService:

    def __init__(self, azure_client: AsyncAzureOpenAI, dial_core_client: DialCoreClient, forwarded_headers: ForwardedHeaders) -> None:
        self.__azure_client: AsyncAzureOpenAI = azure_client
        self.__dial_core_client: DialCoreClient = dial_core_client
        self.__forwarded_headers: ForwardedHeaders = forwarded_headers

    @staticmethod
    def _prepare_custom_fields(items: Iterable[tuple[str, Any]]) -> dict[str, Any] | None:
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
        params: dict[str, Any],
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
        chat_params = self._build_chat_completion_params(
            params, deployment_id, messages, self.__forwarded_headers
        )
        chunks = await self.__azure_client.chat.completions.create(**chat_params)
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
        params: dict[str, Any],
        deployment_id: str,
        messages: list[UserMessageParam | AssistantMessageParam],
        forwarded_headers: ForwardedHeaders,
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

        if forwarded_headers:
            chat_completion_params[EXTRA_HEADERS] = forwarded_headers
            logger.debug("##{}", chat_completion_params)

        return chat_completion_params

    @staticmethod
    def _fix_attachment(attachment: Any) -> None:
        """Bugfix issue#16: if attachment has no data and no url, use reference_url as url."""
        if attachment.data is None and attachment.url is None:
            if attachment.reference_url is None:
                attachment["data"] = ""
            else:
                attachment.url = attachment.reference_url

    async def _consume_stream(
        self,
        chunks: AsyncIterable[ChatCompletionChunk],
        stage_wrapper: BaseStageWrapper | None,
    ) -> _StreamResult:
        result = _StreamResult()
        content_parts: list[str] = []

        if stage_wrapper:
            stage_wrapper.append_stage_content("> #### Response:\n")

        svc = self

        def on_stream_event(event: ChatStreamEvent) -> None:
            if isinstance(event, ChunkUsageFootprint):
                if event.raw_usage is not None:
                    result.usage = event.raw_usage
                if event.statistics is not None:
                    result.statistics = event.statistics
                return
            delta = event
            if (c := delta.content) and c:
                if stage_wrapper:
                    stage_wrapper.append_stage_content(c)
                content_parts.append(c)
            if not delta.custom:
                return
            if delta.custom.sdk_attachments:
                result.extend_attachments(delta.custom.sdk_attachments)
                if stage_wrapper:
                    for attachment in delta.custom.sdk_attachments:
                        svc._fix_attachment(attachment)
                        stage_wrapper.add_stage_attachment(_to_sdk_attachment(attachment))
            elif delta.custom.state is not None:
                result.state = delta.custom.state

        await consume_chat_completion_chunks(
            chunks,
            partial(
                parse_chat_completion_chunk,
                mode=ChatStreamFootprintMode.DEPLOYMENT,
            ),
            on_stream_event,
        )

        result.content = "".join(content_parts)
        return result

    @staticmethod
    def __get_deployment_usage(
        usage: Any,
        statistics: dict | None,
        deployment_id: str,
        deployment_name: str,
    ) -> list[DeploymentUsage] | None:
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
            message["custom_content"] = CustomContentParam(attachments=attachments)
        return message

    async def resolve_attachment_urls(
        self, relative_attachment_urls: list[str] | None
    ) -> list[AttachmentParam]:
        return [await self._resolve_attachment(url) for url in (relative_attachment_urls or [])]

    async def _resolve_attachment(self, file_relative_url: str) -> AttachmentParam:
        fileinfo = await self.__dial_core_client.get_metadata("files/"+file_relative_url)
        return AttachmentParam(
            type=fileinfo.get("content_type", ""),
            title=fileinfo.get("name", None),
            url=fileinfo.get("url", ""),
        )
