class SuppressedAttachmentRegistry:
    """Request-scoped set of attachment URLs that must not appear in the choice.

    Populated by the orchestrator when tool results contain attachments that
    were not promoted to the choice (i.e. not in propagate_types_to_choice).
    Consumed by ChoiceUiSink to filter orchestrator LLM stream attachments.
    A URL's suppression is lifted once that same URL is legitimately propagated
    to the choice, so a later tool call promoting a previously-withheld
    attachment does not leave it permanently blacklisted.
    """

    def __init__(self) -> None:
        self._urls: set[str] = set()

    def suppress(self, url: str) -> None:
        self._urls.add(url)

    def unsuppress(self, url: str) -> None:
        self._urls.discard(url)

    def is_suppressed(self, url: str | None) -> bool:
        return url is not None and url in self._urls
