from abc import ABC, abstractmethod

from aidial_sdk.chat_completion import Attachment, Message


class ToolAttachmentKeepPolicy(ABC):
    """Decides whether a single attachment on a TOOL message should survive
    pre-invocation filtering.

    Each feature module owns a policy for its own tool messages. Policies vote
    by returning ``True`` for attachments they want to keep; an attachment is
    retained if **any** policy votes to keep it.

    Lifecycle: ``prepare()`` is called once per pre-invocation pass so policies
    can build per-batch caches (e.g. allowlists) without recomputing on every
    ``should_keep()`` call.
    """

    def prepare(self, messages: list[Message]) -> None:
        """Hook for per-batch precomputation. Default is a no-op."""

    @abstractmethod
    def should_keep(
        self,
        messages: list[Message],
        message_index: int,
        attachment: Attachment,
    ) -> bool: ...
