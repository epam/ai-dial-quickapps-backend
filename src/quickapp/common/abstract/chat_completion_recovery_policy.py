from abc import ABC, abstractmethod

from aidial_sdk.chat_completion.request import Message


class ChatCompletionRecoveryPolicy(ABC):
    """Mutates ``messages`` in-place to recover from a failed chat completion call.

    Each feature module owns a policy for the errors it knows how to recover from.
    Policies are tried in order; the first to return ``True`` wins and the caller
    retries the failed operation at most once. Return ``False`` if this policy
    cannot handle ``error`` — the next policy is tried, and the original error is
    re-raised if no policy recovers.
    """

    @abstractmethod
    def try_recover(self, messages: list[Message], error: Exception) -> bool: ...
