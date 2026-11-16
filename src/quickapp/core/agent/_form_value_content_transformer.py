import json
import logging

from aidial_sdk.chat_completion import Message
from injector import inject

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.config.application import ApplicationConfig
from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.core.agent.models import STATE_KEY_FORM_SCHEMA_SOURCE_TOOL

logger = logging.getLogger(__name__)

_FORM_VALUE_TAG = "form_value"


def _find_tool_conversation_mode(app_config: ApplicationConfig, tool_name: str | None):
    """conversation_mode of the tool that produced the last form_schema, if identifiable."""
    if tool_name is None:
        return None
    for ts in app_config.tool_sets or []:
        if isinstance(ts, DeploymentToolSet):
            for tool in ts.tools:
                if not getattr(tool, "enabled", True):
                    continue
                fn = getattr(getattr(tool, "open_ai_tool", None), "function", None)
                if getattr(fn, "name", None) == tool_name:
                    return getattr(tool, "conversation_mode", None)
    return None


def _is_resumable(conversation_mode) -> bool:
    return bool(conversation_mode is not None and getattr(conversation_mode, "resumable", False))


def _source_tool_name(messages: list[Message]) -> str | None:
    """Latest form_schema_source_tool marker echoed back by the client in state."""
    source = None
    for message in messages:
        cc = message.custom_content
        if cc is not None and cc.state and STATE_KEY_FORM_SCHEMA_SOURCE_TOOL in cc.state:
            source = cc.state[STATE_KEY_FORM_SCHEMA_SOURCE_TOOL]
    return source


class _FormValueContentTransformer(MessagesTransformer):
    """Inject ``custom_content.form_value`` into the message content for the orchestrator.

    Applies when the tool that produced the last form_schema has no conversation_mode
    (no tool history to carry ``form_value`` to a deployment): the submitted form data
    is appended to the message content as a ``<form_value>`` block instead, so the
    orchestrator keeps it in the conversation. The working copy is modified; the
    request's own messages are left untouched (deployment tools still read
    ``form_value`` from them).
    """

    @inject
    def __init__(self, app_config: ApplicationConfig) -> None:
        self.__app_config = app_config

    async def transform(self, messages: list[Message]) -> list[Message]:
        # Inject only when the tool that produced the form is known and has no
        # conversation_mode: with history, form_value travels to that tool via
        # custom_content; without it, the orchestrator must see the submitted data.
        source_tool = _source_tool_name(messages)
        if source_tool is None:
            return messages
        conversation_mode = _find_tool_conversation_mode(self.__app_config, source_tool)
        if _is_resumable(conversation_mode):
            return messages
        return self._inject(messages)

    def _inject(self, messages: list[Message]) -> list[Message]:
        result: list[Message] = []
        injected = 0
        for message in messages:
            form_value = (
                message.custom_content.form_value if message.custom_content is not None else None
            )
            if form_value is None:
                result.append(message)
                continue
            copied = message.model_copy(deep=True)
            block = f"<{_FORM_VALUE_TAG}>\n{json.dumps(form_value, ensure_ascii=False)}\n</{_FORM_VALUE_TAG}>"
            text = copied.content or ""
            copied.content = f"{text}\n\n{block}" if text else block
            if copied.custom_content is not None:
                copied.custom_content.form_value = None
            result.append(copied)
            injected += 1

        if injected:
            logger.debug("Injected form_value into content of %d message(s)", injected)
        return result
