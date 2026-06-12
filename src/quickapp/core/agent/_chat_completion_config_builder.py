import json
import logging
from typing import Any

from aidial_sdk.chat_completion.request import Message
from injector import inject

from quickapp.core.agent.agent_settings import AgentSettings
from quickapp.core.agent.message_logger import format_openai_message_pipe_tree
from quickapp.core.agent.models import STATE_KEY_ORCHESTRATOR, OpenAiToolConfigDict
from quickapp.common import RESPONSE_FORMAT, ForwardedHeaders
from quickapp.common.abstract.base_transformer import PreInvocationTransformer
from quickapp.common.presentation_settings import PresentationSettings
from quickapp.config.application import ApplicationConfig

logger = logging.getLogger(__name__)


@inject
class _ChatCompletionConfigBuilder:
    def __init__(
        self,
        config: ApplicationConfig,
        tools: list[OpenAiToolConfigDict],
        response_format: RESPONSE_FORMAT,
        pre_invocation_transformers: list[PreInvocationTransformer],
        presentation_settings: PresentationSettings,
        forwarded_headers: ForwardedHeaders,
        agent_settings: AgentSettings,
    ) -> None:
        self.__config: ApplicationConfig = config
        self.__tools: list[OpenAiToolConfigDict] = tools
        self.__response_format = response_format
        self.__pre_invocation_transformers = pre_invocation_transformers
        self.__presentation_settings = presentation_settings
        self.__forwarded_headers = forwarded_headers
        self.__agent_settings = agent_settings

    def build(self, messages: list[Message]) -> dict[str, Any]:
        chat_completion_config = self.__config.orchestrator.deployment.parameters.model_dump(
            exclude_none=True
        )
        prepared_messages = self._prepare_messages(messages)
        payload: dict[str, Any] = {
            "messages": prepared_messages,
            "stream": True,
            "model": self.__config.orchestrator.deployment.deployment_id,
            "tools": self.__tools,
        }

        if self.__response_format:
            logger.debug("Setting response format: %s", self.__response_format)
            if hasattr(self.__response_format, "model_dump"):
                payload["response_format"] = self.__response_format.model_dump(
                    exclude_none=True, mode="json"
                )
            elif isinstance(self.__response_format, dict):
                payload["response_format"] = self.__response_format
            else:
                logger.error(
                    "Unsupported response format type: %s. The response format will not be applied.",
                    type(self.__response_format),
                )

        if self.__presentation_settings.show_usage_statistics:
            payload["stream_options"] = {"include_usage": True}

        if self.__forwarded_headers:
            payload["extra_headers"] = self.__forwarded_headers

        chat_completion_config.update(payload)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Chat completion config: %s", json.dumps(chat_completion_config, ensure_ascii=False)
            )
        return chat_completion_config

    def _prepare_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        transformed_messages = messages
        for transformer in self.__pre_invocation_transformers:
            transformed_messages = transformer.transform(transformed_messages)
        result: list[dict[str, Any]] = []
        for message in transformed_messages:
            msg_dict = message.model_dump(exclude_none=True, mode="json")
            self._promote_orchestrator_state_to_top_level(msg_dict)
            result.append(msg_dict)
        return result

    def _log_messages(self, messages: list[dict[str, Any]]) -> None:
        preview_len = self.__agent_settings.chat_message_log_length
        for idx, msg in enumerate(messages, start=1):
            format_openai_message_pipe_tree(msg, idx, preview_len=preview_len)

    @staticmethod
    def _promote_orchestrator_state_to_top_level(msg_dict: dict[str, Any]) -> None:
        """Before calling the model, promote state.orchestrator to top-level state."""
        custom = msg_dict.get("custom_content")
        if not isinstance(custom, dict):
            return
        state = custom.get("state")
        if not isinstance(state, dict) or STATE_KEY_ORCHESTRATOR not in state:
            return
        orch = state.pop(STATE_KEY_ORCHESTRATOR, None)
        if isinstance(orch, dict):
            state.update(orch)
