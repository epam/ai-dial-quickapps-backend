import asyncio
import logging

from aidial_client import AsyncDial
from aidial_client.helpers.storage_resource import _percent_encode_relative_url
from aidial_client.resources import AsyncMetadata
from aidial_client.types.chat.request_param import AttachmentParam
from injector import inject

from quickapp.common.attachment_processing_utils import inferred_mime_type_for_file_context_url
from quickapp.common.dial_settings import DialSettings
from quickapp.common.file_reference_pattern import strip_file_prefix
from quickapp.common.project_context import PROJECT_CONTEXT
from quickapp.common.url_classification import (
    UrlScheme,
    classify_url,
    to_relative_project_url,
    unsupported_scheme_error,
)
from quickapp.common.utils import filename_from_url_path
from quickapp.dial_core_services.dial_file_promoter import DialFilePromoter
from quickapp.shared.home_path.home_path_resolver import HomePathResolver

logger = logging.getLogger(__name__)


@inject
class AttachmentResolver:
    """Resolve outbound attachment URLs into ``AttachmentParam`` objects.

    Dispatches on URL classification and the deployment's
    ``features.url_attachments`` capability:

    * **DIAL** — read metadata via ``dial_client.metadata.get`` and emit a
      ``url=`` attachment.
    * **Project chat: a file of the request's project, or a home-relative path** (resolved
      under the project's ``artifacts/``) — emit a ``url=`` attachment as is, with no v1
      metadata call (v1 can't read ``projects/`` URLs). A deployment that can't read
      ``projects/`` URLs answers with its own error, surfaced as a tool error.
    * **External + ``supports_url_attachments``** — emit a ``reference_url=``
      attachment; the deployment fetches the bytes itself, no QuickApps egress.
    * **External + not supported** — materialise via :class:`DialFilePromoter`
      (fetch + upload to caller's bucket) and emit a ``url=`` attachment.
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
        home_resolver: HomePathResolver,
        project: PROJECT_CONTEXT,
    ) -> None:
        self.__dial_client = dial_client
        self.__base_url = dial_settings.url
        self.__file_promoter = file_promoter
        self.__home_resolver = home_resolver
        self.__project = project

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
        bare = to_relative_project_url(
            strip_file_prefix(file_relative_url), self.__base_url, self.__project
        )
        scheme = classify_url(bare, self.__base_url, self.__project)

        if self.__project is not None:
            if scheme == UrlScheme.DIAL_APPDIR_RELATIVE:
                return _pass_through(await self.__home_resolver.resolve_appdata_url(bare))
            if scheme == UrlScheme.DIAL and self.__project.contains(bare):
                return _pass_through(_percent_encode_relative_url(bare))

        if scheme == UrlScheme.DIAL:
            metadata: AsyncMetadata = self.__dial_client.metadata
            fileinfo = await metadata.get("files", bare)
            return AttachmentParam(
                type=fileinfo.content_type or "",
                title=fileinfo.name or "",
                url=fileinfo.url or "",
            )

        if scheme == UrlScheme.EXTERNAL:
            if supports_url_attachments:
                return AttachmentParam(
                    reference_url=bare,
                    url=bare,
                    title=filename_from_url_path(bare) or bare,
                    type="*/*",
                )
            meta = await self.__file_promoter.promote(bare, parameter_name="attachment_urls")
            return AttachmentParam(
                type=meta.content_type or "",
                title=meta.name or "",
                url=meta.url or "",
            )

        raise unsupported_scheme_error(bare, parameter_name="attachment_urls")


def _pass_through(url: str) -> AttachmentParam:
    """A ``url=`` attachment for a project file, typed and titled from its name."""
    return AttachmentParam(
        type=inferred_mime_type_for_file_context_url(url),
        title=filename_from_url_path(url) or url,
        url=url,
    )
