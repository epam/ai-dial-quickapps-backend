import logging
from collections.abc import AsyncIterable, Iterable
from typing import Any

from aidial_client import AsyncDial
from aidial_client.resources import AsyncMetadata
from aidial_client.types.chat import response as dial_client_models
from aidial_client.types.chat.request_param import (
    AssistantMessageParam,
    AttachmentParam,
    CustomContentParam,
    UserMessageParam,
)
from aidial_sdk import chat_completion as dial_sdk_models
from injector import inject
from pydantic import BaseModel, Field

from quickapp.common import CompletionResult, ForwardedHeaders
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.deployment_usage import DeploymentUsage
from quickapp.common.file_reference_pattern import strip_file_prefix
from quickapp.common.utils import to_plain_dict
from quickapp.dial_deployment_tooling.constants import (
    ATTACHMENT_PARAM,
    CONFIGURATION,
    CONTENT_PARAM,
    EXTRA_BODY,
    EXTRA_HEADERS,
    PROPAGATED_STAGE_NAME_SEPARATOR,
)
from quickapp.dial_deployment_tooling.stage_propagation_models import parse_stages

logger = logging.getLogger(__name__)


def _to_sdk_attachment(attachment: dial_client_models.Attachment) -> dial_sdk_models.Attachment:
    return dial_sdk_models.Attachment(**attachment.model_dump())


def _to_sdk_attachments_from_any(attachments: list[Any] | None) -> list[dial_sdk_models.Attachment]:
    """Convert attachment-like items (from subagent stage deltas) to SDK Attachment list."""
    if not attachments:
        return []
    result: list[dial_sdk_models.Attachment] = []
    for a in attachments:
        try:
            if hasattr(a, "model_dump"):
                result.append(dial_sdk_models.Attachment(**a.model_dump()))
            elif isinstance(a, dict):
                result.append(dial_sdk_models.Attachment(**a))
        except Exception:
            continue
    return result


class _StreamResult(BaseModel):
    content: str = ""
    attachments: list[dial_sdk_models.Attachment] | None = None
    state: dict[str, Any] | None = None
    usage: dial_client_models.CompletionUsage | None = None
    statistics: dict[str, Any] = Field(default_factory=dict)

    def extend_attachments(self, attachments: list[dial_client_models.Attachment]) -> None:
        if self.attachments is None:
            self.attachments = []
        self.attachments.extend(_to_sdk_attachment(a) for a in attachments)


@inject
class DialCompletionService:

    def __init__(self, dial_client: AsyncDial, forwarded_headers: ForwardedHeaders) -> None:
        self.__dial_client: AsyncDial = dial_client
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
        propagate_stages: bool = False,
        tool_stage_display_name: str | None = None,
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
        chunks = await self.__dial_client.chat.completions.create(**chat_params)
        result = await self._consume_stream(
            chunks,
            stage_wrapper,
            propagate_stages=propagate_stages,
            tool_stage_display_name=tool_stage_display_name,
        )

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
        chunks: AsyncIterable[dial_client_models.ChatCompletionChunk],
        stage_wrapper: BaseStageWrapper | None,
        propagate_stages: bool = False,
        tool_stage_display_name: str | None = None,
    ) -> _StreamResult:
        result = _StreamResult()
        content_parts: list[str] = []
        # Accumulate by stage index: same index = same stage (append name, content, attachments; set status)
        # Value: (name_parts, content_parts, attachments, status)
        propagated_stages: dict[int, tuple[list[str], list[str], list[Any], str | None]] = {}

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
                            stage_wrapper.add_stage_attachment(_to_sdk_attachment(attachment))
                if delta.custom_content and delta.custom_content.state:
                    result.state = delta.custom_content.state

                if propagate_stages and delta.custom_content:
                    raw_stages = getattr(delta.custom_content, "stages", None)
                    parsed = parse_stages(raw_stages)
                    for i, sub in enumerate(parsed):
                        # Subagent identifies stage by index; fall back to position in list when index is missing
                        idx = sub.index if sub.index is not None else i
                        if idx not in propagated_stages:
                            propagated_stages[idx] = ([], [], [], None)
                        name_parts, content_parts_list, atts, _ = propagated_stages[idx]
                        if sub.name_part():
                            name_parts.append(sub.name_part())
                        if sub.content:
                            content_parts_list.append(sub.content)
                        if sub.attachments:
                            atts.extend(sub.attachments)
                        if sub.status is not None:
                            propagated_stages[idx] = (
                                name_parts,
                                content_parts_list,
                                atts,
                                sub.status,
                            )

            if chunk.usage:
                result.usage = chunk.usage
            result.statistics = (
                (chunk.model_extra or {}).get("statistics", {}).get("usage_per_model", {})
            )

        result.content = "".join(content_parts)

        if (
            propagate_stages
            and propagated_stages
            and stage_wrapper
            and hasattr(stage_wrapper, "create_propagated_stage")
        ):
            try:
                prefix = (tool_stage_display_name or "").strip()
                count = 0
                for idx in sorted(propagated_stages.keys()):
                    name_parts, content_parts_list, atts, _status = propagated_stages[idx]
                    stage_name = "".join(name_parts).strip() if name_parts else f"Stage {idx + 1}"
                    prefixed_name = (
                        (prefix + PROPAGATED_STAGE_NAME_SEPARATOR + stage_name).strip()
                        if prefix
                        else stage_name
                    )
                    content = "".join(content_parts_list)
                    sdk_attachments = _to_sdk_attachments_from_any(atts)
                    stage_wrapper.create_propagated_stage(prefixed_name, content, sdk_attachments)
                    count += 1
                logger.debug(
                    "Stage propagation: created %d propagated stage(s) for subagent",
                    count,
                )
            except Exception as e:
                logger.warning(
                    "Stage propagation failed, falling back to single stage: %s",
                    e,
                    exc_info=True,
                )
                prefix_fb = (tool_stage_display_name or "").strip()
                fallback_parts = []
                for idx in sorted(propagated_stages.keys()):
                    name_parts_fb, content_parts_list_fb, _, _ = propagated_stages[idx]
                    stage_name_fb = "".join(name_parts_fb).strip() or f"Stage {idx + 1}"
                    prefixed_name_fb = (
                        (prefix_fb + PROPAGATED_STAGE_NAME_SEPARATOR + stage_name_fb).strip()
                        if prefix_fb
                        else stage_name_fb
                    )
                    fallback_parts.append(
                        f"**{prefixed_name_fb}**\n{''.join(content_parts_list_fb)}"
                    )
                fallback_content = "\n\n".join(fallback_parts)
                if stage_wrapper and fallback_content:
                    stage_wrapper.append_stage_content("\n\n> #### Subagent stages\n\n")
                    stage_wrapper.append_stage_content(fallback_content)

        return result

    @staticmethod
    def __get_deployment_usage(
        usage: dial_client_models.CompletionUsage | None,
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
        metadata: AsyncMetadata = self.__dial_client.metadata
        fileinfo = await metadata.get("files", strip_file_prefix(file_relative_url))
        return AttachmentParam(
            type=fileinfo.content_type or "",
            title=fileinfo.name,
            url=fileinfo.url or "",
        )
