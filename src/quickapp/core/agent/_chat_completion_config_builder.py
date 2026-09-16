import json
import logging
from typing import Any

from aidial_sdk.chat_completion.request import Message
from aidial_sdk.exceptions import InvalidRequestError
from injector import inject

from quickapp.common import RESPONSE_FORMAT, ForwardedHeaders
from quickapp.common.abstract.base_transformer import PreInvocationTransformer
from quickapp.common.payload_logging import log_payload, payloads_enabled, summarize_roles
from quickapp.common.presentation_settings import PresentationSettings
from quickapp.config.application import ApplicationConfig
from quickapp.core.agent._tool_choice_holder import _ToolChoiceHolder
from quickapp.core.agent.lazy_loaded_tools_holder import LazyLoadedToolsHolder
from quickapp.core.agent.models import STATE_KEY_ORCHESTRATOR, OpenAiToolConfigDict
from quickapp.core.agent.orchestrator_capabilities import OrchestratorCapabilities

logger = logging.getLogger(__name__)

REASONING_EFFORT_PARAM = "reasoning_effort"


@inject
class _ChatCompletionConfigBuilder:
    def __init__(
        self,
        config: ApplicationConfig,
        tools: list[OpenAiToolConfigDict],
        response_format: RESPONSE_FORMAT,
        tool_choice_holder: _ToolChoiceHolder,
        pre_invocation_transformers: list[PreInvocationTransformer],
        presentation_settings: PresentationSettings,
        forwarded_headers: ForwardedHeaders,
        lazy_loaded_tools_holder: LazyLoadedToolsHolder,
        capabilities: OrchestratorCapabilities,
    ) -> None:
        self.__config: ApplicationConfig = config
        self.__tools: list[OpenAiToolConfigDict] = tools
        self.__response_format = response_format
        self.__tool_choice_holder = tool_choice_holder
        self.__pre_invocation_transformers = pre_invocation_transformers
        self.__presentation_settings = presentation_settings
        self.__forwarded_headers = forwarded_headers
        self.__lazy_loaded_tools_holder = lazy_loaded_tools_holder
        self.__capabilities: OrchestratorCapabilities = capabilities

    def build(self, messages: list[Message]) -> dict[str, Any]:
        chat_completion_config = self.__config.orchestrator.deployment.parameters.model_dump(
            exclude_none=True
        )
        self._drop_unsupported_reasoning_effort(chat_completion_config)
        prepared_messages = self._prepare_messages(messages)
        all_tools = self._merge_tools()
        payload: dict[str, Any] = {
            "messages": prepared_messages,
            "stream": True,
            "model": self.__config.orchestrator.deployment.deployment_id,
            "tools": all_tools,
        }

        self._apply_response_format(payload)
        self._apply_tool_choice(payload)

        if self.__presentation_settings.show_usage_statistics:
            payload["stream_options"] = {"include_usage": True}

        if self.__forwarded_headers:
            payload["extra_headers"] = self.__forwarded_headers

        chat_completion_config.update(payload)
        self._log_result(chat_completion_config, prepared_messages, all_tools)
        return chat_completion_config

    def _merge_tools(self) -> list[OpenAiToolConfigDict]:
        eager_names: set[str] = {t.get("function", {}).get("name", "") for t in self.__tools}
        lazy_tools = [
            t
            for t in self.__lazy_loaded_tools_holder.get_all()
            if t.get("function", {}).get("name", "") not in eager_names
        ]
        return self.__tools + lazy_tools

    def _apply_response_format(self, payload: dict[str, Any]) -> None:
        if not self.__response_format:
            return
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

    def _log_result(
        self,
        chat_completion_config: dict[str, Any],
        prepared_messages: list[dict[str, Any]],
        all_tools: list[OpenAiToolConfigDict],
    ) -> None:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Chat completion config: messages=%d, roles=%s, tools=%d (eager=%d, lazy=%d), response_format=%s, "
                "model=%s, forwarded_headers=%s",
                len(prepared_messages),
                summarize_roles(prepared_messages),
                len(all_tools),
                len(self.__tools),
                len(all_tools) - len(self.__tools),
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

    def _drop_unsupported_reasoning_effort(self, chat_completion_config: dict[str, Any]) -> None:
        """Remove a `reasoning_effort` the deployment does not advertise.

        Sending it anyway is rejected upstream with an opaque `400` that reaches the user as a
        generic "request was rejected as invalid". `_OrchestratorDeploymentInitializer` reports
        the same condition in the Initialization issues stage, so the drop is not silent.
        """
        reasoning_effort = chat_completion_config.get(REASONING_EFFORT_PARAM)
        if reasoning_effort is None or self.__capabilities.supports_reasoning_effort(
            reasoning_effort
        ):
            return
        del chat_completion_config[REASONING_EFFORT_PARAM]

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
