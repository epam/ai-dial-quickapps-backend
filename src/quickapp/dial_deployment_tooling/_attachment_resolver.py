import asyncio
import logging

from aidial_client import AsyncDial
from aidial_client.resources import AsyncMetadata
from aidial_client.types.chat.request_param import AttachmentParam
from aidial_client.types.metadata import FileItem, FileMetadata
from injector import inject

from quickapp.common.data_uri import is_data_uri
from quickapp.common.dial_settings import DialSettings
from quickapp.common.file_reference_pattern import strip_file_prefix
from quickapp.common.url_classification import UrlScheme, classify_url, unsupported_scheme_error
from quickapp.common.utils import filename_from_url_path
from quickapp.dial_core_services.dial_file_promoter import DialFilePromoter
from quickapp.dial_deployment_tooling.constants import ATTACHMENT_PARAM

logger = logging.getLogger(__name__)


@inject
class AttachmentResolver:
    """Resolve outbound attachment URLs into ``AttachmentParam`` objects.

    Dispatches on URL classification and the deployment's
    ``features.url_attachments`` capability:

    * **DIAL** — read metadata via ``dial_client.metadata.get`` and emit a
      ``url=`` attachment.
    * **External + ``supports_url_attachments``** — emit a ``reference_url=``
      attachment; the deployment fetches the bytes itself, no QuickApps egress.
    * **External + not supported** — materialise via :class:`DialFilePromoter`
      (fetch + upload to caller's bucket) and emit a ``url=`` attachment.
    * **``data:`` URI** — decode the inline content once via :class:`DialFilePromoter`
      and emit a ``url=`` attachment. A deployment needs a fetchable URL, and the
      payload must not survive past this point.
    * **Unsupported scheme** — raise ``InvalidToolCallParameterException``.

    Sibling resolutions in a single tool call run in parallel; one failure
    surfaces as the raised exception, the others still complete (no
    cancellation cascade).
    """

    def __init__(
        self,
        dial_client: AsyncDial,
        dial_settings: DialSettings,
        file_promoter: DialFilePromoter,
    ) -> None:
        self.__dial_client = dial_client
        self.__base_url = dial_settings.url
        self.__file_promoter = file_promoter

    async def resolve_attachment_urls(
        self,
        relative_attachment_urls: list[str] | None,
        *,
        supports_url_attachments: bool = False,
    ) -> list[AttachmentParam]:
        if not relative_attachment_urls:
            return []
        results = await asyncio.gather(
            *(
                self._resolve_attachment(url, supports_url_attachments)
                for url in relative_attachment_urls
            ),
            return_exceptions=True,
        )
        resolved: list[AttachmentParam] = []
        for result in results:
            if isinstance(result, BaseException):
                raise result
            resolved.append(result)
        return resolved

    async def _resolve_attachment(
        self, file_relative_url: str, supports_url_attachments: bool
    ) -> AttachmentParam:
        bare = strip_file_prefix(file_relative_url)

        # Checked ahead of classify_url, which reports every non-http(s) scheme as
        # UNSUPPORTED. Inline content is accepted only here — the other classify_url
        # consumers must keep rejecting it.
        if is_data_uri(bare):
            meta = await self.__file_promoter.promote(bare, parameter_name=ATTACHMENT_PARAM)
            return self._param_from_metadata(meta)

        scheme = classify_url(bare, self.__base_url)

        if scheme == UrlScheme.DIAL:
            metadata: AsyncMetadata = self.__dial_client.metadata
            fileinfo = await metadata.get("files", bare)
            return self._param_from_metadata(fileinfo)

        if scheme == UrlScheme.EXTERNAL:
            if supports_url_attachments:
                return AttachmentParam(
                    reference_url=bare,
                    url=bare,
                    title=filename_from_url_path(bare) or bare,
                    type="*/*",
                )
            meta = await self.__file_promoter.promote(bare, parameter_name=ATTACHMENT_PARAM)
            return self._param_from_metadata(meta)

        raise unsupported_scheme_error(file_relative_url, parameter_name=ATTACHMENT_PARAM)

    @staticmethod
    def _param_from_metadata(meta: FileMetadata | FileItem) -> AttachmentParam:
        return AttachmentParam(
            type=meta.content_type or "",
            title=meta.name or "",
            url=meta.url or "",
        )
