import json
import logging
from typing import Any, cast

from aidial_client.types.chat.request_param import (
    AssistantMessageParam,
    AttachmentParam,
    CustomContentParam,
    UserMessageParam,
)
from aidial_sdk.chat_completion import CustomContent, Role
from aidial_sdk.chat_completion.request import Attachment as SdkAttachment
from injector import AssistedBuilder

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.payload_logging import log_payload
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.utils import to_plain_dict
from quickapp.config.dial_deployment import DialDeploymentParameters
from quickapp.config.tools.base import ConfigurableSchemaSimpleType, JsonTypeEnum, OpenAiToolConfig
from quickapp.config.tools.deployment import (
    ContentPropagation,
    ConversationMode,
    DialDeploymentTool,
)
from quickapp.dial_deployment_tooling._attachment_resolver import AttachmentResolver
from quickapp.dial_deployment_tooling.constants import (
    ATTACHMENT_PARAM,
    CONFIGURATION,
    CONTENT_PARAM,
)
from quickapp.dial_deployment_tooling.dial_completion_service import DialCompletionService

from .deployment_stage_wrapper import DeploymentStageWrapper

logger = logging.getLogger(__name__)


class BaseDeploymentTool(StagedBaseTool):

    def __init__(
        self,
        application_id: str,
        application_name: str,
        tool_config: DialDeploymentTool,
        content_propagation: ContentPropagation | None,
        dial_completion_service: DialCompletionService,
        attachment_resolver: AttachmentResolver,
        messages_mixin: MessagesMixin,
        perf_timer: PerformanceTimer,
        stage_wrapper_builder: AssistedBuilder[DeploymentStageWrapper],
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            argument_transformers=argument_transformers,
            **kwargs,
        )
        self.__application_id: str = application_id
        self.__application_name: str = application_name
        self.__dial_completion_service: DialCompletionService = dial_completion_service
        self.__attachment_resolver: AttachmentResolver = attachment_resolver
        self.__content_propagation: ContentPropagation | None = content_propagation
        if content_propagation and content_propagation.propagate_history:
            logger.warning(
                "The 'propagate_history' parameter is deprecated and will be removed in a future release. "
                "Use 'conversation_mode: stateful' instead."
            )
        self.__messages_mixin: MessagesMixin = messages_mixin

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None,
        tool_call_id: str | None = None,
        attachment_urls: list[str] | None = None,
        **kwargs,
    ) -> ToolCallResult:
        tool_config = cast(DialDeploymentTool, self.tool_config)
        session_id: str | None = kwargs.pop("session_id", None)
        is_stateful = (
            self.__content_propagation is not None
            and self.__content_propagation.conversation_mode == ConversationMode.STATEFUL
        )
        is_first_call = is_stateful and session_id is None
        if is_first_call:
            session_id = tool_call_id
            logger.info("Stateful tool first call — assigned session_id=%s", session_id)
        elif is_stateful and session_id:
            logger.info("Stateful tool follow-up — session_id=%s", session_id)
        history = None
        if self.__content_propagation and (
            self.__content_propagation.propagate_history or is_stateful
        ):
            history = await self._extract_tool_history(
                tool_config.open_ai_tool.function.name, session_id=session_id
            )
        result = await self.__dial_completion_service.complete_request_async(
            kwargs,
            self.__application_id,
            self.__application_name,
            stage_wrapper,
            attachment_urls,
            history=history,
            supports_url_attachments=tool_config.supports_url_attachments,
        )
        if is_first_call and session_id:
            result.content = result.content + f"\n\n[session_id: {session_id}]"
        return result

    _SESSION_ID_PARAM = ConfigurableSchemaSimpleType(
        type=JsonTypeEnum.string,
        description=(
            "The session identifier returned at the end of a previous response from this tool. "
            "Pass it back unchanged to continue that conversation thread. "
            "Omit to start a new independent thread."
        ),
    )

    def enrich_openai_tool_schema(self, open_ai_tool: OpenAiToolConfig) -> OpenAiToolConfig:
        if not (
            self.__content_propagation
            and self.__content_propagation.conversation_mode == ConversationMode.STATEFUL
        ):
            return open_ai_tool
        if "session_id" not in open_ai_tool.function.parameters.properties:
            open_ai_tool.function.parameters.properties["session_id"] = self._SESSION_ID_PARAM
        return open_ai_tool

    @staticmethod
    def _sdk_attachment_to_param(attachment: SdkAttachment) -> AttachmentParam:
        return AttachmentParam(
            **attachment.model_dump(  # type: ignore[typeddict-item]
                include=set(AttachmentParam.__annotations__),
                exclude_none=True,
            )
        )

    async def _extract_tool_history(
        self,
        tool_name: str,
        session_id: str | None = None,
    ) -> list[UserMessageParam | AssistantMessageParam]:
        if not tool_name:
            return []

        messages = self.__messages_mixin.messages

        # Build map: tool_call_id -> (content, custom_content)
        tool_result_by_id: dict[str, tuple[str, CustomContent | None]] = {}
        for msg in messages:
            if msg.role == Role.TOOL and msg.tool_call_id:
                raw = msg.content
                content = "" if raw is None else (str(raw) if not isinstance(raw, str) else raw)
                tool_result_by_id[msg.tool_call_id] = (content, msg.custom_content)

        # Walk ASSISTANT messages, find completed tool_calls matching tool_name
        history: list[UserMessageParam | AssistantMessageParam] = []
        for msg in messages:
            if msg.role != Role.ASSISTANT or not msg.tool_calls:
                continue

            for tc in msg.tool_calls:
                if tc.function.name != tool_name:
                    continue

                # When session_id is provided, match calls that are either:
                # - the thread anchor (tc.id == session_id): the first call, identified by
                #   the tool_call_id the backend returned to the LLM as the session identifier
                # - a follow-up (args["session_id"] == session_id): the LLM echoed it back
                if session_id is not None:
                    try:
                        call_args = json.loads(tc.function.arguments)
                        is_anchor = tc.id == session_id
                        is_followup = call_args.get("session_id") == session_id
                        if not (is_anchor or is_followup):
                            continue
                    except (json.JSONDecodeError, AttributeError):
                        if tc.id != session_id:
                            continue

                result_entry = tool_result_by_id.get(tc.id)
                if result_entry is None:
                    # Current call — its TOOL result hasn't been appended yet
                    continue

                tool_content, tool_custom_content = result_entry

                user_msg = await self._build_user_message_from_tool_call(tc.function.arguments)
                if user_msg is not None:
                    history.append(user_msg)

                if tool_content or tool_custom_content:
                    assistant_msg = self._build_assistant_message(
                        tool_content or "", tool_custom_content
                    )
                    history.append(assistant_msg)

        return history

    async def _build_user_message_from_tool_call(
        self, raw_arguments: str
    ) -> UserMessageParam | None:
        try:
            args = json.loads(raw_arguments)
            query: str = args.get(CONTENT_PARAM, "")
            attachment_urls: list[str] | None = args.get(ATTACHMENT_PARAM)
        except (json.JSONDecodeError, AttributeError):
            return None

        if not query and not attachment_urls:
            return None

        user_msg = UserMessageParam(role="user", content=query or "")
        if attachment_urls:
            tool_config = cast(DialDeploymentTool, self.tool_config)
            resolved = await self.__attachment_resolver.resolve_attachment_urls(
                attachment_urls,
                supports_url_attachments=tool_config.supports_url_attachments,
            )
            if resolved:
                user_msg["custom_content"] = CustomContentParam(attachments=resolved)
        return user_msg

    @classmethod
    def _build_assistant_message(
        cls, content: str, custom_content: CustomContent | None
    ) -> AssistantMessageParam:
        assistant_msg = AssistantMessageParam(role="assistant", content=content)

        if custom_content:
            cc_param = CustomContentParam()
            if custom_content.attachments:
                cc_param["attachments"] = [
                    cls._sdk_attachment_to_param(a) for a in custom_content.attachments
                ]
            if custom_content.state is not None:
                cc_param["state"] = custom_content.state
            if cc_param:
                assistant_msg["custom_content"] = cc_param

        return assistant_msg

    async def _pre_process_params(self, **kwargs: Any) -> dict[str, Any]:
        kwargs = await super()._pre_process_params(**kwargs)

        prepared: dict[str, Any] = {}

        tool_config = cast(DialDeploymentTool, self.tool_config)
        config_param_names = tool_config.deployment._configuration_param_names

        # If tool config defines defaults, normalize them first
        params = tool_config.deployment.parameters
        self._merge_to_prepared_params(params, prepared)

        # Split LLM kwargs: configuration params vs standard params
        config_kwargs: dict[str, Any] = {}
        other_kwargs: dict[str, Any] = {}
        for k, v in kwargs.items():
            if k in config_param_names:
                config_kwargs[k] = v
            else:
                other_kwargs[k] = v

        # Wrap configuration params into custom_fields.configuration, merging with defaults
        if config_kwargs:
            custom_fields = prepared.get("custom_fields", {})
            if not isinstance(custom_fields, dict):
                custom_fields = {}
            configuration = custom_fields.get(CONFIGURATION, {})
            if not isinstance(configuration, dict):
                configuration = {}
            configuration.update(config_kwargs)
            custom_fields[CONFIGURATION] = configuration
            prepared["custom_fields"] = custom_fields

        # Standard params override defaults as flat keys
        prepared.update(other_kwargs)

        logger.debug("Pre-processed tool parameters: keys=%s", list(prepared))
        log_payload(logger, "Pre-processed tool parameters: %s", prepared)

        return prepared

    @staticmethod
    def _merge_to_prepared_params(params: DialDeploymentParameters, prepared: dict[str, Any]):
        """Merge deployment parameters into a plain dict. Grouping into extra_body is done in DialCompletionService."""
        params_dict = to_plain_dict(params)
        if isinstance(params_dict, dict):
            for key, value in params_dict.items():
                if value is None or value == {}:
                    continue
                prepared[key] = value
