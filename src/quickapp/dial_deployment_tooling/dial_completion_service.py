import logging
from collections.abc import AsyncIterable, Iterable
from typing import Any

from aidial_client.types.chat.request_param import (
    AssistantMessageParam,
    AttachmentParam,
    CustomContentParam,
    UserMessageParam,
)
from injector import inject
from openai.types.chat import ChatCompletionChunk

from quickapp.common import (
    DEPLOYMENT_AZURE_CLIENT,
    DIAL_API_KEY,
    CompletionResult,
    ForwardedHeaders,
)
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.chat_completion_stream.exceptions import ChatStreamHandlerError
from quickapp.common.chat_completion_stream.handler import (
    ChatCompletionStreamHandler,
    DeploymentStreamStrategyConfig,
)
from quickapp.common.chat_completion_stream.stream_result import ChatStreamAccumulator
from quickapp.common.deployment_usage import DeploymentUsage
from quickapp.common.dial_core_client import DialCoreClient
from quickapp.common.dial_settings import DialSettings
from quickapp.common.utils import to_plain_dict
from quickapp.dial_deployment_tooling.constants import (
    ATTACHMENT_PARAM,
    CONFIGURATION,
    CONTENT_PARAM,
    EXTRA_BODY,
    EXTRA_HEADERS,
)

logger = logging.getLogger(__name__)


@inject
class DialCompletionService:

    def __init__(
        self,
        azure_client: DEPLOYMENT_AZURE_CLIENT,
        dial_settings: DialSettings,
        api_key: DIAL_API_KEY,
        forwarded_headers: ForwardedHeaders,
    ) -> None:
        self.__azure_client = azure_client
        self.__base_url: str = dial_settings.url
        self.__api_key: DIAL_API_KEY = api_key
        self.__forwarded_headers: ForwardedHeaders = forwarded_headers
        self.__stream_handler = ChatCompletionStreamHandler()

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
            attachments=result.attachments_or_none,
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
            "model": deployment_id,
            "stream": True,
            "messages": messages,
        }
        logger.debug("##%s", chat_completion_params)

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
            logger.debug("##%s", chat_completion_params)

        return chat_completion_params

    async def _consume_stream(
        self,
        chunks: AsyncIterable[ChatCompletionChunk],
        stage_wrapper: BaseStageWrapper | None,
    ) -> ChatStreamAccumulator:
        try:
            return await self.__stream_handler.process_deployment_stream(
                chunks=chunks,
                config=DeploymentStreamStrategyConfig(stage_wrapper=stage_wrapper),
            )
        except ChatStreamHandlerError:
            logger.exception("Deployment stream handling failed.")
            raise

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
        attachments = []
        if relative_attachment_urls:
            async with DialCoreClient(self.__api_key, self.__base_url) as dial_core_client:
                for url in relative_attachment_urls:
                    attachments.append(await self._resolve_attachment(dial_core_client, url))
        return attachments

    async def _resolve_attachment(
        self, dial_core_client: DialCoreClient, file_relative_url: str
    ) -> AttachmentParam:
        fileinfo = await dial_core_client.get_metadata(file_relative_url)
        return AttachmentParam(
            type=fileinfo.get("content_type", ""),
            title=fileinfo.get("name", ""),
            url=fileinfo.get("url", ""),
        )
