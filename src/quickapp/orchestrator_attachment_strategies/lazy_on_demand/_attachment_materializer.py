"""Resolve an attachment url into a form the orchestrator can fetch."""

import logging

from aidial_sdk.chat_completion import Attachment
from injector import inject

from quickapp.common.dial_settings import DialSettings
from quickapp.common.url_classification import UrlScheme, classify_url
from quickapp.dial_core_services.dial_file_promoter import DialFilePromoter

logger = logging.getLogger(__name__)


@inject
class _AttachmentMaterializer:
    """Promotes an external attachment url to a durable DIAL file the orchestrator
    can read (via :class:`DialFilePromoter`). Request-scoped and shared by the
    synthetic injector and the explicit get-content tool, so a url promoted on one
    path is reused on the other.
    """

    def __init__(
        self,
        dial_promoter: DialFilePromoter,
        dial_settings: DialSettings,
    ) -> None:
        self.__dial_promoter: DialFilePromoter = dial_promoter
        self.__dial_url: str = dial_settings.url

    def classify(self, url: str) -> UrlScheme:
        return classify_url(url, self.__dial_url)

    async def materialize_external(self, url: str) -> Attachment:
        """Promote an external url to a DIAL file and return it as an attachment.
        Raises ``InvalidToolCallParameterException`` if promotion is blocked or fails
        (callers decide whether to skip or surface a retry).
        """
        meta = await self.__dial_promoter.promote(url, parameter_name="attachment_url")
        return Attachment(url=meta.url, type=meta.content_type or "", title=meta.name or "")
