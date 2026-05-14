import copy
import json
from typing import Any

from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role
from aidial_sdk.chat_completion.request import FunctionCall, ToolCall

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import _make_call_id
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._tool_configs import (
    GET_CONTENT_TOOL_CONFIG,
)


class _AttachmentGetContentInjector(MessagesTransformer):
    call_id_prefix: str = "s_"

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
    def _build_tool_result_payload(attachment: Attachment) -> str:
        url = str(attachment.url or "").strip()
        title = str(attachment.title) if attachment.title else url.rsplit("/", 1)[-1]
        content_type = attachment.type or "application/octet-stream"
        return json.dumps(
            {"ok": True, "url": url, "title": title, "type": content_type},
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

    async def transform(self, messages: list[Message]) -> list[Message]:
        last_user = self._last_user_with_attachments(messages)
        if last_user is None:
            return messages

        last_user_idx, last_user_msg = last_user
        assert last_user_msg.custom_content is not None
        attachments = list(last_user_msg.custom_content.attachments or [])
        if not attachments:
            return messages

        tool_name = GET_CONTENT_TOOL_CONFIG.open_ai_tool.function.name
        result_messages = list(messages)
        insert_idx = last_user_idx + 1
        inserted = 0

        for attachment in attachments:
            url = str(attachment.url or "").strip()
            if not url:
                continue
            arguments = {"attachment_url": url}
            if self._has_pair_in_current_turn(
                result_messages, last_user_idx + 1, tool_name, arguments
            ):
                continue

            payload = self._build_tool_result_payload(attachment)
            call_id, _args_hash = _make_call_id(self.call_id_prefix, tool_name, arguments, payload)
            assistant_msg, tool_msg = self._build_pair(
                tool_name=tool_name,
                call_id=call_id,
                arguments=arguments,
                payload=payload,
                attachment=attachment,
            )
            at = insert_idx + inserted
            result_messages[at:at] = [assistant_msg, tool_msg]
            inserted += 2

        return result_messages
