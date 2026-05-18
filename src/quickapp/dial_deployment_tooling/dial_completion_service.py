import asyncio
import logging
from collections.abc import AsyncIterable
from typing import Any

from aidial_client import AsyncDial
from aidial_client.resources import AsyncMetadata
from aidial_client.types.chat.request_param import (
    AssistantMessageParam,
    AttachmentParam,
    CustomContentParam,
    UserMessageParam,
)
from injector import inject
from openai.types.chat import ChatCompletionChunk

from quickapp.common import DEPLOYMENT_AZURE_CLIENT, DIAL_API_KEY, ForwardedHeaders, ToolCallResult
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.chat_completion_stream.exceptions import ChatStreamHandlerError
from quickapp.common.chat_completion_stream.handler import (
    ChatCompletionStreamHandler,
    ChatStreamConfig,
)
from quickapp.common.chat_completion_stream.stream_result import ChatStreamAccumulator
from quickapp.common.deployment_usage import DeploymentUsage
from quickapp.common.dial_settings import DialSettings
from quickapp.common.file_reference_pattern import strip_file_prefix
from quickapp.common.tool_timeout_resolver import ToolTimeoutResolver
from quickapp.common.tool_timeout_utils import translate_timeout
from quickapp.common.url_classification import UrlScheme, classify_url, unsupported_scheme_error
from quickapp.common.utils import filename_from_url_path
from quickapp.dial_deployment_tooling.constants import (
    ATTACHMENT_PARAM,
    CONTENT_PARAM,
    EXTRA_BODY,
    EXTRA_HEADERS,
)
from quickapp.file_transfer._dial_file_promoter import DialFilePromoter

logger = logging.getLogger(__name__)


@inject
class DialCompletionService:

    def __init__(
        self,
        azure_client: DEPLOYMENT_AZURE_CLIENT,
        dial_settings: DialSettings,
        api_key: DIAL_API_KEY,
        dial_client: AsyncDial,
        forwarded_headers: ForwardedHeaders,
        stream_handler: ChatCompletionStreamHandler,
        timeout_resolver: ToolTimeoutResolver,
        file_promoter: DialFilePromoter,
    ) -> None:
        self.__dial_client: AsyncDial = dial_client
        self.__azure_client = azure_client
        self.__base_url: str = dial_settings.url
        self.__api_key: DIAL_API_KEY = api_key
        self.__forwarded_headers: ForwardedHeaders = forwarded_headers
        self.__stream_handler = stream_handler
        self.__timeout_resolver: ToolTimeoutResolver = timeout_resolver
        self.__file_promoter = file_promoter

    async def complete_request_async(
        self,
        params: dict[str, Any],
        deployment_id: str,
        deployment_name: str,
        stage_wrapper: BaseStageWrapper | None,
        relative_attachment_urls: list[str] | None = None,
        history: list[UserMessageParam | AssistantMessageParam] | None = None,
        supports_url_attachments: bool = False,
    ) -> ToolCallResult:
        # Expect params to be pre-processed by BaseDeploymentTool._pre_process_params
        content = params.get(CONTENT_PARAM, "")
        if not content:
            logger.warning(
                "Tool call content is empty. Check the tool configuration,"
                " it should use `query` parameter"
            )

        timeout = self.__timeout_resolver.resolve()
        async with translate_timeout(deployment_name, timeout):
            messages = await self.__build_request_messages(
                content, relative_attachment_urls, history, supports_url_attachments
            )
            chat_params = self._build_chat_completion_params(
                params, deployment_id, messages, self.__forwarded_headers
            )
            chunks = await self.__azure_client.chat.completions.create(**chat_params)
            result = await self._consume_stream(chunks, stage_wrapper)

        return ToolCallResult(
            content=result.content,
            content_type="text/markdown",
            # check if result.attachments: would return false for empty array
            attachments=result.attachments_or_none,
            state=result.state,
            usage=self.__get_deployment_usage(result.usage, deployment_id, deployment_name),
        )

    @staticmethod
    def _build_chat_completion_params(
        params: dict[str, Any],
        deployment_id: str,
        messages: list[UserMessageParam | AssistantMessageParam],
        forwarded_headers: ForwardedHeaders,
    ) -> dict[str, Any]:
        chat_completion_params: dict[str, Any] = {
            "model": deployment_id,
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

        return chat_completion_params

    async def _consume_stream(
        self,
        chunks: AsyncIterable[ChatCompletionChunk],
        stage_wrapper: BaseStageWrapper | None,
    ) -> ChatStreamAccumulator:
        try:
            return await self.__stream_handler.process_stream(
                chunks=chunks,
                config=ChatStreamConfig(stage_wrapper=stage_wrapper),
            )
        except ChatStreamHandlerError:
            logger.exception("Deployment stream handling failed.")
            raise

    @staticmethod
    def __get_deployment_usage(
        usage: Any,
        deployment_id: str,
        deployment_name: str,
    ) -> list[DeploymentUsage] | None:
        if usage:
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
        supports_url_attachments: bool = False,
    ) -> list[UserMessageParam | AssistantMessageParam]:
        messages: list[UserMessageParam | AssistantMessageParam] = []
        if history:
            messages.extend(history)
        messages.append(
            await self.__user_message_from_content_and_attachments(
                content, relative_attachment_urls, supports_url_attachments
            )
        )
        return messages

    async def __user_message_from_content_and_attachments(
        self,
        content,
        relative_attachment_urls: list[str] | None = None,
        supports_url_attachments: bool = False,
    ) -> UserMessageParam:
        message = UserMessageParam(role="user", content=content)
        attachments = await self.resolve_attachment_urls(
            relative_attachment_urls, supports_url_attachments
        )
        if attachments and len(attachments) > 0:
            message["custom_content"] = CustomContentParam(attachments=attachments)
        return message

    async def resolve_attachment_urls(
        self,
        relative_attachment_urls: list[str] | None,
        supports_url_attachments: bool = False,
    ) -> list[AttachmentParam]:
        if not relative_attachment_urls:
            return []
        results = await asyncio.gather(
            *(
                self._resolve_attachment(url, supports_url_attachments)
                for url in relative_attachment_urls
            ),
            return_exceptions=True,
        )
        resolved: list[AttachmentParam] = []
        for result in results:
            if isinstance(result, BaseException):
                raise result
            resolved.append(result)
        return resolved

    async def _resolve_attachment(
        self, file_relative_url: str, supports_url_attachments: bool
    ) -> AttachmentParam:
        bare = strip_file_prefix(file_relative_url)
        scheme = classify_url(bare, self.__base_url)

        if scheme == UrlScheme.DIAL:
            metadata: AsyncMetadata = self.__dial_client.metadata
            fileinfo = await metadata.get("files", bare)
            return AttachmentParam(
                type=fileinfo.content_type or "",
                title=fileinfo.name or "",
                url=fileinfo.url or "",
            )

        if scheme == UrlScheme.EXTERNAL:
            if supports_url_attachments:
                return AttachmentParam(
                    reference_url=bare,
                    title=filename_from_url_path(bare) or bare,
                )
            meta = await self.__file_promoter.promote(bare, parameter_name="attachment_urls")
            return AttachmentParam(
                type=meta.content_type or "",
                title=meta.name or "",
                url=meta.url or "",
            )

        raise unsupported_scheme_error(file_relative_url, parameter_name="attachment_urls")
