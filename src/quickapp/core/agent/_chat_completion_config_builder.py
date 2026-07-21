import json
import logging
from typing import Any

from aidial_sdk.chat_completion.request import Message
from aidial_sdk.exceptions import InvalidRequestError
from injector import inject

from quickapp.common import RESPONSE_FORMAT, ForwardedHeaders
from quickapp.common.abstract.base_transformer import PreInvocationTransformer
from quickapp.common.payload_logging import log_payload, payloads_enabled, summarize_roles
from quickapp.config.application import ApplicationConfig
from quickapp.core.agent._tool_choice_holder import _ToolChoiceHolder
from quickapp.core.agent.models import STATE_KEY_ORCHESTRATOR, OpenAiToolConfigDict

logger = logging.getLogger(__name__)


@inject
class _ChatCompletionConfigBuilder:
    def __init__(
        self,
        config: ApplicationConfig,
        tools: list[OpenAiToolConfigDict],
        response_format: RESPONSE_FORMAT,
        tool_choice_holder: _ToolChoiceHolder,
        pre_invocation_transformers: list[PreInvocationTransformer],
        forwarded_headers: ForwardedHeaders,
    ) -> None:
        self.__config: ApplicationConfig = config
        self.__tools: list[OpenAiToolConfigDict] = tools
        self.__response_format = response_format
        self.__tool_choice_holder = tool_choice_holder
        self.__pre_invocation_transformers = pre_invocation_transformers
        self.__forwarded_headers = forwarded_headers

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
            logger.debug("Setting response format (type=%s)", type(self.__response_format).__name__)
            log_payload(logger, "Response format: %s", self.__response_format)
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

        self._apply_tool_choice(payload)

        # Always request usage from the orchestrator model so the app can report an
        # accurate top-level ``usage`` regardless of whether the Usage Statistics
        # stage (a separate presentation opt-in) is shown.
        payload["stream_options"] = {"include_usage": True}

        if self.__forwarded_headers:
            payload["extra_headers"] = self.__forwarded_headers

        chat_completion_config.update(payload)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Chat completion config: messages=%d, roles=%s, tools=%d, response_format=%s, "
                "model=%s, forwarded_headers=%s",
                len(prepared_messages),
                summarize_roles(prepared_messages),
                len(self.__tools),
                "response_format" in chat_completion_config,
                chat_completion_config.get("model"),
                # Header NAMES only — forwarded X-* header values are never logged, even
                # under the payload switch (they may carry auth-adjacent material).
                list(self.__forwarded_headers or []),
            )
        # Guard the (potentially large) serialization: log_payload no-ops when the switch
        # is off, but its json.dumps argument would otherwise still run every request.
        # The dump excludes extra_headers entirely — header values are never emitted.
        if payloads_enabled():
            loggable = {k: v for k, v in chat_completion_config.items() if k != "extra_headers"}
            log_payload(
                logger, "Chat completion config: %s", json.dumps(loggable, ensure_ascii=False)
            )
        return chat_completion_config

    def _apply_tool_choice(self, payload: dict[str, Any]) -> None:
        tool_choice = self.__tool_choice_holder.consume()
        if tool_choice is None:
            return
        requires_tool = tool_choice == "required" or (
            hasattr(tool_choice, "type") and tool_choice.type == "function"
        )
        if requires_tool and not self.__tools:
            raise InvalidRequestError(
                message="tool_choice requires at least one tool to be configured",
                display_message=(
                    "Cannot enforce tool_choice: no tools are available. "
                    "Configure at least one tool set or use tool_choice='auto'."
                ),
            )
        if hasattr(tool_choice, "model_dump"):
            payload["tool_choice"] = tool_choice.model_dump(exclude_none=True, mode="json")
        else:
            payload["tool_choice"] = tool_choice

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
