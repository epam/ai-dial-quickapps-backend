"""Resolve an allowed attachment url into a form the orchestrator can fetch."""

import logging

from aidial_sdk.chat_completion import Attachment
from injector import inject

from quickapp.common.attachment_processing_utils import normalize_attachment_url_argument
from quickapp.common.dial_settings import DialSettings
from quickapp.common.url_classification import UrlScheme, classify_url
from quickapp.dial_core_services.dial_file_promoter import DialFilePromoter
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._promoted_attachment_urls import (
    PromotedAttachmentUrls,
)

logger = logging.getLogger(__name__)


@inject
class _AttachmentMaterializer:
    """Promotes an external attachment url to a durable DIAL file the orchestrator
    can read (via :class:`DialFilePromoter`), recording the minted url in
    :class:`PromotedAttachmentUrls`. Request-scoped and shared by the synthetic
    injector and the explicit get-content tool, so a url promoted on one path is
    reused on the other.
    """

    def __init__(
        self,
        dial_promoter: DialFilePromoter,
        dial_settings: DialSettings,
        promoted_urls: PromotedAttachmentUrls,
    ) -> None:
        self.__dial_promoter: DialFilePromoter = dial_promoter
        self.__dial_url: str = dial_settings.url
        self.__promoted_urls: PromotedAttachmentUrls = promoted_urls

    def classify(self, url: str) -> UrlScheme:
        return classify_url(url, self.__dial_url)

    async def materialize_external(self, url: str) -> Attachment:
        """Promote an external url to a DIAL file, record it, and return it as an
        attachment. Raises ``InvalidToolCallParameterException`` if promotion is
        blocked or fails (callers decide whether to skip or surface a retry).
        """
        meta = await self.__dial_promoter.promote(url, parameter_name="attachment_url")
        self.__promoted_urls.urls.add(normalize_attachment_url_argument(str(meta.url or "")))
        return Attachment(url=meta.url, type=meta.content_type or "", title=meta.name or "")
