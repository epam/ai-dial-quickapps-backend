import base64
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client.types.chat.request_param import AttachmentParam

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.file_reference_pattern import strip_file_prefix
from quickapp.dial_core_services.dial_file_promoter import DialFilePromoter
from quickapp.dial_deployment_tooling._attachment_resolver import AttachmentResolver


def _make_resolver(
    *,
    dial_client: MagicMock | None = None,
    file_promoter: MagicMock | None = None,
    base_url: str = "https://dial.example",
) -> AttachmentResolver:
    if dial_client is None:
        dial_client = MagicMock()
        dial_client.metadata.get = AsyncMock()
    if file_promoter is None:
        file_promoter = MagicMock(spec=DialFilePromoter)
        file_promoter.promote = AsyncMock()
    dial_settings = MagicMock(url=base_url)
    return AttachmentResolver(
        dial_client=dial_client,
        dial_settings=dial_settings,
        file_promoter=file_promoter,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "file_relative_url",
    [
        "file:base64::files/images/chart.png",
        "files/images/chart.png",
    ],
)
async def test_dial_path_queries_dial_client_metadata(file_relative_url):
    """DIAL paths call ``dial_client.metadata.get('files', stripped_path)`` and
    skip the promoter entirely."""
    fileinfo = MagicMock()
    fileinfo.content_type = "image/png"
    fileinfo.name = "photo.png"
    fileinfo.url = "files/resolved.png"

    dial_client = MagicMock()
    dial_client.metadata.get = AsyncMock(return_value=fileinfo)
    promoter = MagicMock(spec=DialFilePromoter)
    promoter.promote = AsyncMock()

    resolver = _make_resolver(dial_client=dial_client, file_promoter=promoter)
    result = await resolver._resolve_attachment(file_relative_url, supports_url_attachments=False)

    dial_client.metadata.get.assert_called_once_with("files", strip_file_prefix(file_relative_url))
    assert result == AttachmentParam(type="image/png", title="photo.png", url="files/resolved.png")
    promoter.promote.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_with_supports_emits_reference_url():
    """External URL on a deployment that advertises ``url_attachments`` emits
    ``reference_url`` — no QuickApps fetch, no DIAL metadata read."""
    dial_client = MagicMock()
    dial_client.metadata.get = AsyncMock()
    promoter = MagicMock(spec=DialFilePromoter)
    promoter.promote = AsyncMock()

    resolver = _make_resolver(dial_client=dial_client, file_promoter=promoter)
    url = "https://example.com/path/whitepaper.pdf"
    result = await resolver._resolve_attachment(url, supports_url_attachments=True)

    assert result.get("reference_url") == url
    assert result.get("title") == "whitepaper.pdf"
    assert result.get("url") == url
    assert result.get("type") == "*/*"
    promoter.promote.assert_not_awaited()
    dial_client.metadata.get.assert_not_called()


@pytest.mark.asyncio
async def test_external_without_supports_promotes_to_dial_file():
    """External URL on a deployment that doesn't advertise ``url_attachments``
    goes through ``DialFilePromoter`` and is emitted as a regular DIAL ``url``."""
    upload_meta = MagicMock()
    upload_meta.url = "https://dial.example/v1/files/promoted.pdf"
    upload_meta.name = "external.pdf"
    upload_meta.content_type = "application/pdf"
    promoter = MagicMock(spec=DialFilePromoter)
    promoter.promote = AsyncMock(return_value=upload_meta)

    resolver = _make_resolver(file_promoter=promoter)
    result = await resolver._resolve_attachment(
        "https://example.com/external.pdf", supports_url_attachments=False
    )

    promoter.promote.assert_awaited_once_with(
        "https://example.com/external.pdf", parameter_name="attachment_urls"
    )
    assert result == AttachmentParam(
        type="application/pdf",
        title="external.pdf",
        url="https://dial.example/v1/files/promoted.pdf",
    )


@pytest.mark.asyncio
async def test_unsupported_scheme_raises_invalid_param():
    resolver = _make_resolver()
    with pytest.raises(InvalidToolCallParameterException):
        await resolver._resolve_attachment("ftp://example.com/x", supports_url_attachments=False)


@pytest.mark.asyncio
async def test_promoter_exception_propagates_unchanged():
    """The promoter already wraps fetch failures in ``InvalidToolCallParameterException``;
    the resolver just lets them propagate."""
    promoter = MagicMock(spec=DialFilePromoter)
    promoter.promote = AsyncMock(
        side_effect=InvalidToolCallParameterException(
            parameter_name="attachment_urls", message="External URL fetching is disabled"
        )
    )
    resolver = _make_resolver(file_promoter=promoter)
    with pytest.raises(InvalidToolCallParameterException):
        await resolver._resolve_attachment("https://x", supports_url_attachments=False)


@pytest.mark.asyncio
async def test_resolve_attachment_urls_returns_empty_for_none_or_empty():
    resolver = _make_resolver()
    assert await resolver.resolve_attachment_urls(None) == []
    assert await resolver.resolve_attachment_urls([]) == []


@pytest.mark.asyncio
async def test_resolve_attachment_urls_preserves_order_for_mixed_list():
    """A list mixing DIAL paths and external URLs returns one AttachmentParam
    per input in the original order."""
    fileinfo = MagicMock()
    fileinfo.content_type = "application/pdf"
    fileinfo.name = "internal.pdf"
    fileinfo.url = "files/bucket/internal.pdf"
    dial_client = MagicMock()
    dial_client.metadata.get = AsyncMock(return_value=fileinfo)
    promoter = MagicMock(spec=DialFilePromoter)
    promoter.promote = AsyncMock()

    resolver = _make_resolver(dial_client=dial_client, file_promoter=promoter)
    result = await resolver.resolve_attachment_urls(
        [
            "files/bucket/internal.pdf",
            "https://example.com/external.pdf",
        ],
        supports_url_attachments=True,
    )

    assert len(result) == 2
    assert result[0].get("url") == "files/bucket/internal.pdf"
    assert result[1].get("reference_url") == "https://example.com/external.pdf"


@pytest.mark.asyncio
async def test_resolve_attachment_urls_first_failure_surfaces_sibling_completions():
    """When one URL fails, the others still complete (no cancellation cascade)
    and the failure is raised once gather collects everything."""
    fileinfo = MagicMock()
    fileinfo.content_type = "text/plain"
    fileinfo.name = "ok.txt"
    fileinfo.url = "files/ok.txt"
    dial_client = MagicMock()
    dial_client.metadata.get = AsyncMock(return_value=fileinfo)

    resolver = _make_resolver(dial_client=dial_client)
    with pytest.raises(InvalidToolCallParameterException):
        await resolver.resolve_attachment_urls(
            [
                "files/ok.txt",
                "ftp://bad.example/x",
            ],
            supports_url_attachments=False,
        )
    # DIAL metadata was still queried for the good URL despite the sibling
    # eventually raising.
    dial_client.metadata.get.assert_called_once()


class TestDataUriAttachments:
    """A ``data:`` URI reaches the resolver whenever the model emits one directly
    (the ``file:data::`` form is normalized upstream in ``BaseDeploymentTool``).
    The deployment needs a fetchable URL, so the payload is promoted."""

    @staticmethod
    def _promoted() -> MagicMock:
        meta = MagicMock()
        meta.content_type = "application/pdf"
        meta.name = "inline.pdf"
        meta.url = "files/bucket/inline.pdf"
        return meta

    @pytest.mark.asyncio
    @pytest.mark.parametrize("supports_url_attachments", [True, False])
    async def test_promoted_to_a_dial_file_url(self, supports_url_attachments):
        encoded = base64.b64encode(b"%PDF-1.7 body").decode()
        data_uri = f"data:application/pdf;base64,{encoded}"
        dial_client = MagicMock()
        dial_client.metadata.get = AsyncMock()
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock(return_value=self._promoted())

        resolver = _make_resolver(dial_client=dial_client, file_promoter=promoter)
        result = await resolver._resolve_attachment(
            data_uri, supports_url_attachments=supports_url_attachments
        )

        # Even a deployment advertising url_attachments cannot fetch a data: URI,
        # so it is promoted rather than forwarded as a reference_url.
        promoter.promote.assert_awaited_once_with(data_uri, parameter_name="attachment_urls")
        dial_client.metadata.get.assert_not_called()
        assert result == AttachmentParam(
            type="application/pdf", title="inline.pdf", url="files/bucket/inline.pdf"
        )
        assert result.get("reference_url") is None

    @pytest.mark.asyncio
    async def test_file_data_prefix_form_resolves_as_a_dial_path(self):
        """The history-rebuild path sees raw, untransformed arguments; the bare path
        behind the prefix is what matters there."""
        fileinfo = MagicMock()
        fileinfo.content_type = "application/pdf"
        fileinfo.name = "doc.docx"
        fileinfo.url = "files/bucket/doc.docx"
        dial_client = MagicMock()
        dial_client.metadata.get = AsyncMock(return_value=fileinfo)
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock()

        resolver = _make_resolver(dial_client=dial_client, file_promoter=promoter)
        result = await resolver._resolve_attachment(
            "file:data::files/bucket/doc.docx", supports_url_attachments=False
        )

        dial_client.metadata.get.assert_called_once_with("files", "files/bucket/doc.docx")
        promoter.promote.assert_not_awaited()
        assert result.get("url") == "files/bucket/doc.docx"

    @pytest.mark.asyncio
    async def test_promotion_failure_message_carries_no_payload(self):
        encoded = base64.b64encode(b"z" * 4096).decode()
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock(
            side_effect=InvalidToolCallParameterException(
                parameter_name="attachment_urls",
                message="Inline data: content for parameter `attachment_urls` is too large.",
            )
        )

        resolver = _make_resolver(file_promoter=promoter)
        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await resolver.resolve_attachment_urls(
                [f"data:application/pdf;base64,{encoded}"], supports_url_attachments=False
            )

        assert encoded not in excinfo.value.message
