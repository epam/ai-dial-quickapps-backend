"""Request-scoped registry of DIAL urls produced by promoting external attachments."""


class PromotedAttachmentUrls:
    """Per-request set of DIAL urls minted by promoting external attachments.

    Unioned into the get-content allow-set by ``_GetContentKeepPolicy`` so a
    promoted attachment isn't stripped right after being attached (its url is not
    one of the request's admin/user urls).
    """

    __slots__ = ("urls",)

    def __init__(self) -> None:
        self.urls: set[str] = set()
