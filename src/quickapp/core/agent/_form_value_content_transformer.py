import json
import logging
from typing import Any

from aidial_sdk.chat_completion import Message
from injector import inject

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.form_utils import form_source_tool_name_before, form_value_of
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.config.tools.deployment import DialDeploymentTool

logger = logging.getLogger(__name__)

_FORM_VALUE_TAG = "form_value"


class _FormValueContentTransformer(MessagesTransformer):
    """Inject ``custom_content.form_value`` into message content for the orchestrator.

    For every message carrying ``form_value``, the form's source tool (the initiator — the
    tool whose call produced the form) is resolved from the history *before* that message.
    When that tool's config has ``propagate_form_value_to_content: true``, the submitted data
    is appended to the message's content as a ``<form_value>`` block, so the orchestrator sees
    it — regardless of ``conversation_mode.resumable`` (a resumable source additionally
    receives the value via ``custom_content`` in its own request).

    Injection covers *all* messages with ``form_value`` (not just the last one): dropping
    older ones would lose data and break the KV cache (the message prefix must stay stable
    across turns). The working copy is modified; the request's own messages are left
    untouched (deployment tools still read ``form_value`` from them).
    """

    @inject
    def __init__(self, tools: list[StagedBaseTool]) -> None:
        self.__tools_by_name = {tool.openai_function_name(): tool for tool in tools}

    async def transform(self, messages: list[Message]) -> list[Message]:
        result = [self._transform_message(messages, i) for i in range(len(messages))]
        injected = sum(1 for new, old in zip(result, messages) if new is not old)
        if injected:
            logger.debug("Injected form_value into content of %d message(s)", injected)
        return result

    def _transform_message(self, messages: list[Message], index: int) -> Message:
        message = messages[index]
        form_value = form_value_of(message)
        if form_value is None:
            return message
        source_name = form_source_tool_name_before(messages, index)
        if source_name is None:
            return message
        if not self._propagate_to_content(self.__tools_by_name.get(source_name)):
            return message
        return self._with_form_value_block(message, form_value)

    @staticmethod
    def _propagate_to_content(tool: StagedBaseTool | None) -> bool:
        if tool is None or not isinstance(tool.tool_config, DialDeploymentTool):
            return False
        return bool(tool.tool_config.propagate_form_value_to_content)

    @staticmethod
    def _with_form_value_block(message: Message, form_value: Any) -> Message:
        copied = message.model_copy(deep=True)
        payload = json.dumps(form_value, ensure_ascii=False)
        block = f"<{_FORM_VALUE_TAG}>\n{payload}\n</{_FORM_VALUE_TAG}>"
        text = copied.content or ""
        copied.content = f"{text}\n\n{block}" if text else block
        return copied
