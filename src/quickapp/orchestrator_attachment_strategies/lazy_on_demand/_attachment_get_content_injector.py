import copy
import hashlib
import json
import logging
from typing import Any

from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role
from aidial_sdk.chat_completion.request import FunctionCall, ToolCall
from injector import inject

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.attachment_processing_utils import attachment_mime_type
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.file_reference_pattern import to_file_url_reference
from quickapp.common.url_classification import UrlScheme
from quickapp.common.utils import matches_type
from quickapp.core.agent import OrchestratorCapabilities
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._attachment_materializer import (
    _AttachmentMaterializer,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._tool_configs import (
    GET_CONTENT_TOOL_CONFIG,
)

logger = logging.getLogger(__name__)


def _make_call_id(call_id_prefix: str, tool_name: str, arguments: dict, content: str) -> str:
    def _hash6(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:6]

    args_hash = _hash6(json.dumps(arguments, sort_keys=True))
    return f"{call_id_prefix}{tool_name}_{args_hash}_{_hash6(content)}"


@inject
class _AttachmentGetContentInjector(MessagesTransformer):
    call_id_prefix: str = "s_"

    def __init__(
        self,
        orchestrator_capabilities: OrchestratorCapabilities,
        materializer: _AttachmentMaterializer,
    ) -> None:
        self.__orchestrator_capabilities: OrchestratorCapabilities = orchestrator_capabilities
        self.__materializer: _AttachmentMaterializer = materializer

    @staticmethod
    def _last_user_with_attachments(messages: list[Message]) -> tuple[int, Message] | None:
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if (
                msg.role == Role.USER
                and msg.custom_content is not None
                and bool(msg.custom_content.attachments)
            ):
                return i, msg
        return None

    @staticmethod
    def _parse_arguments(arguments: str) -> dict[str, Any] | None:
        try:
            data = json.loads(arguments)
        except (TypeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _has_pair_in_current_turn(
        self,
        messages: list[Message],
        current_turn_start: int,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> bool:
        for i in range(current_turn_start, len(messages)):
            msg = messages[i]
            if msg.role != Role.ASSISTANT or not msg.tool_calls:
                continue
            for tc in msg.tool_calls:
                if tc.function is None or tc.id is None:
                    continue
                if tc.function.name != tool_name:
                    continue
                parsed = self._parse_arguments(tc.function.arguments)
                if parsed != arguments:
                    continue
                if any(
                    candidate.role == Role.TOOL and candidate.tool_call_id == tc.id
                    for candidate in messages[i + 1 :]
                ):
                    return True
        return False

    @staticmethod
    def _build_tool_result_payload(attachment: Attachment, display_url: str) -> str:
        # display_url is what the model sees; the promoted DIAL url is only on `attachment`.
        title = str(attachment.title) if attachment.title else display_url.rsplit("/", 1)[-1]
        content_type = attachment.type or "application/octet-stream"
        return json.dumps(
            {"ok": True, "url": display_url, "title": title, "type": content_type},
            ensure_ascii=False,
        )

    @staticmethod
    def _build_pair(
        tool_name: str,
        call_id: str,
        arguments: dict[str, Any],
        payload: str,
        attachment: Attachment,
    ) -> tuple[Message, Message]:
        assistant_msg = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(
                    id=call_id,
                    type="function",
                    function=FunctionCall(
                        name=tool_name,
                        arguments=json.dumps(arguments),
                    ),
                )
            ],
        )
        tool_msg = Message(
            role=Role.TOOL,
            content=payload,
            tool_call_id=call_id,
            custom_content=CustomContent(attachments=[copy.deepcopy(attachment)]),
        )
        return assistant_msg, tool_msg

    async def _resolve_deliverable_attachment(self, attachment: Attachment) -> Attachment | None:
        """Resolve an attachment to a fetchable form, or ``None`` to skip it.

        DIAL attachments pass through; external ones are promoted to a DIAL file.
        ``None`` (undeliverable: promotion blocked/failed or unsupported scheme)
        tells the caller to emit no misleading success pair.
        """
        url = str(attachment.url or "").strip()
        if not url:
            return None
        scheme = self.__materializer.classify(url)
        if scheme == UrlScheme.DIAL:
            return attachment
        if scheme == UrlScheme.EXTERNAL:
            return await self._promote_external(attachment, url)
        logger.info("get_content injector: skipping attachment with unsupported url scheme")
        return None

    async def _promote_external(self, attachment: Attachment, url: str) -> Attachment | None:
        """Promote an external attachment url to a DIAL file, or ``None`` if promotion
        is blocked (policy / SSRF / size) so the caller emits no misleading pair.
        """
        try:
            promoted = await self.__materializer.materialize_external(url)
        except InvalidToolCallParameterException as exc:
            logger.info(
                "get_content injector: skipping external attachment, promotion blocked (%s)",
                exc,
            )
            return None
        return Attachment(
            url=promoted.url,
            type=promoted.type or attachment.type,
            title=attachment.title or promoted.title,
        )

    async def transform(self, messages: list[Message]) -> list[Message]:
        last_user_msg_with_attachments = self._last_user_with_attachments(messages)
        if last_user_msg_with_attachments is None:
            return messages

        last_user_idx, last_user_msg = last_user_msg_with_attachments
        if last_user_msg.custom_content is None:
            return messages
        attachments = list(last_user_msg.custom_content.attachments or [])
        if not attachments:
            return messages

        tool_name = GET_CONTENT_TOOL_CONFIG.open_ai_tool.function.name
        result_messages = list(messages)
        insert_idx = last_user_idx + 1
        inserted = 0

        input_attachment_types = self.__orchestrator_capabilities.input_attachment_types
        for attachment in attachments:
            original_url = str(attachment.url or "").strip()
            if not original_url:
                continue
            # Cheap MIME pre-gate before any network egress (external urls with no
            # guessable type are skipped here).
            if not matches_type(attachment_mime_type(attachment), input_attachment_types):
                continue
            deliverable = await self._resolve_deliverable_attachment(attachment)
            if deliverable is None:
                continue
            # Re-gate on the resolved content type (may differ from the filename guess).
            if not matches_type(attachment_mime_type(deliverable), input_attachment_types):
                continue
            # The synthetic call is a few-shot example the model imitates, so the
            # argument uses the `file:url::` convention — a bare url would teach the
            # model to drop the prefix on this and other file tools.
            arguments = {"attachment_url": to_file_url_reference(original_url)}
            if self._has_pair_in_current_turn(
                result_messages, last_user_idx + 1, tool_name, arguments
            ):
                continue

            payload = self._build_tool_result_payload(deliverable, display_url=original_url)
            call_id = _make_call_id(self.call_id_prefix, tool_name, arguments, payload)
            assistant_msg, tool_msg = self._build_pair(
                tool_name=tool_name,
                call_id=call_id,
                arguments=arguments,
                payload=payload,
                attachment=deliverable,
            )
            at = insert_idx + inserted
            result_messages[at:at] = [assistant_msg, tool_msg]
            inserted += 2

        return result_messages
