from abc import ABC, abstractmethod

from aidial_sdk.chat_completion.request import Message


class ChatCompletionRecoveryPolicy(ABC):
    """Mutates ``messages`` in-place to recover from a failed chat completion call.

    Each feature module owns a policy for the errors it knows how to recover from.
    Policies are invoked in registration order; **every** policy's ``try_recover`` is
    called. ``ChatCompletionRecoveryService`` retries the failed operation at most once per
    request if **any** policy returns ``True``. Return ``False`` if this policy cannot
    handle ``error``; the original error is re-raised if no policy recovers.
    """

    @abstractmethod
    def try_recover(self, messages: list[Message], error: Exception) -> bool: ...
