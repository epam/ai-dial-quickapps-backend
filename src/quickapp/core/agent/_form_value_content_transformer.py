import json
import logging

from aidial_sdk.chat_completion import Message
from injector import inject

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.form_utils import (
    find_tool,
    find_tool_conversation_mode,
    form_source_tool_name_before,
    is_resumable,
)
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.config.tools.deployment import DialDeploymentTool

logger = logging.getLogger(__name__)

_FORM_VALUE_TAG = "form_value"


class _FormValueContentTransformer(MessagesTransformer):
    """Inject ``custom_content.form_value`` into message content for the orchestrator.

    For every message carrying ``form_value``, the form's source tool is resolved from
    the history *before* that message (assistant message ``form_schema`` matched by content
    to the tool message schema → initiator tool call name). When the source tool is not
    resumable **and** its config has ``propagate_form_value_to_content: true``, the submitted
    data is appended to that message's content as a ``<form_value>`` block, so the
    orchestrator keeps it in the conversation. When the source tool is resumable, the value
    travels to that tool via ``custom_content`` instead and no injection happens.

    Injection covers *all* messages with ``form_value`` (not just the last one): dropping
    older ones would lose data and break the KV cache (the message prefix must stay stable
    across turns). The working copy is modified; the request's own messages are left
    untouched (deployment tools still read ``form_value`` from them).
    """

    @inject
    def __init__(self, tools: list[StagedBaseTool]) -> None:
        self.__tools = tools

    async def transform(self, messages: list[Message]) -> list[Message]:
        result: list[Message] = []
        injected = 0
        for i, message in enumerate(messages):
            form_value = (
                message.custom_content.form_value if message.custom_content is not None else None
            )
            if form_value is None:
                result.append(message)
                continue
            source_tool = form_source_tool_name_before(messages, i)
            tool = find_tool(self.__tools, source_tool)
            conversation_mode = find_tool_conversation_mode(self.__tools, source_tool)
            if is_resumable(conversation_mode):
                result.append(message)
                continue
            if not self._propagate_to_content(tool):
                result.append(message)
                continue
            copied = message.model_copy(deep=True)
            block = f"<{_FORM_VALUE_TAG}>\n{json.dumps(form_value, ensure_ascii=False)}\n</{_FORM_VALUE_TAG}>"
            text = copied.content or ""
            copied.content = f"{text}\n\n{block}" if text else block
            result.append(copied)
            injected += 1

        if injected:
            logger.debug("Injected form_value into content of %d message(s)", injected)
        return result

    @staticmethod
    def _propagate_to_content(tool: StagedBaseTool | None) -> bool:
        if tool is None or not isinstance(tool.tool_config, DialDeploymentTool):
            return False
        return bool(tool.tool_config.propagate_form_value_to_content)
