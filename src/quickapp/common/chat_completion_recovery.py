import logging

from injector import inject

from quickapp.common.abstract.chat_completion_recovery_policy import ChatCompletionRecoveryPolicy
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.stage_close_registry import DeferredStageCloseRegistry

logger = logging.getLogger(__name__)

# Log labels for recoverable-failure call sites (one recovery retry per request total).
CHAT_COMPLETION_CREATE_RETRY_SCOPE = "chat_completion_create"
STREAM_ACCUMULATION_RETRY_SCOPE = "stream_accumulation"


@inject
class ChatCompletionRecoveryService:
    """Runs chat-completion recovery policies for the current request.

    Request-scoped. At most one successful recovery per request; callers retry their operation
    in a ``while True`` loop after ``apply_message_recovery`` returns without raising.
    """

    def __init__(
        self,
        messages: MessagesMixin,
        policies: list[ChatCompletionRecoveryPolicy],
        deferred_stage_close_registry: DeferredStageCloseRegistry,
    ) -> None:
        self.__messages = messages
        self.__policies = policies
        self.__deferred_stage_close_registry = deferred_stage_close_registry
        self.__recovery_retry_used = False

    def apply_message_recovery(self, error: Exception, retry_scope: str) -> None:
        """Mutate messages and allow one retry after a recoverable chat-completion failure.

        Call from a ``except (BadRequestError, APIError)`` handler that re-enters its loop when
        this method returns normally. Each registered policy's ``try_recover`` is invoked; if
        any returns ``True``, deferred stage UI is synced with the updated TOOL messages and
        ``__recovery_retry_used`` is set.

        Args:
            error: Passed to policies and re-raised when recovery cannot proceed.
            retry_scope: Log label only (e.g. ``CHAT_COMPLETION_CREATE_RETRY_SCOPE``); does not
                grant a separate retry budget.

        Raises:
            error: If no policy recovers, or if recovery already succeeded once on this request.
        """
        if self.__recovery_retry_used:
            logger.exception(
                "Chat completion failed again after message recovery retry. Scope: %s",
                retry_scope,
            )
            raise error

        messages = self.__messages.messages
        recovered = any(policy.try_recover(messages, error) for policy in self.__policies)
        if not recovered:
            logger.exception(
                "Chat completion failed with BadRequest/APIError; message recovery did not "
                "apply. Scope: %s",
                retry_scope,
            )
            raise error

        self.__deferred_stage_close_registry.sync_deferred_stage_ui_with_tool_messages(messages)
        self.__recovery_retry_used = True
        logger.warning(
            "Chat completion failed with %s; message recovery applied, retrying once. " "Scope: %s",
            type(error).__name__,
            retry_scope,
        )
