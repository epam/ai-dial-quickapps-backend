class SuppressedAttachmentRegistry:
    """Request-scoped set of attachment URLs that must not appear in the choice.

    Populated by the orchestrator when tool results contain attachments that
    were not promoted to the choice (i.e. not in propagate_types_to_choice).
    Consumed by ChoiceUiSink to filter orchestrator LLM stream attachments.
    """

    def __init__(self) -> None:
        self._urls: set[str] = set()

    def suppress(self, url: str) -> None:
        self._urls.add(url)

    def is_suppressed(self, url: str | None) -> bool:
        return url is not None and url in self._urls
