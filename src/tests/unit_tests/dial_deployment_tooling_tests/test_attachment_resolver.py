from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client.types.chat.request_param import AttachmentParam

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.file_reference_pattern import strip_file_prefix
from quickapp.common.project_context import ProjectContext
from quickapp.dial_core_services.dial_file_promoter import DialFilePromoter
from quickapp.dial_deployment_tooling._attachment_resolver import AttachmentResolver
from quickapp.shared.home_path.home_path_resolver import HomePathResolver
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_service

_PROJECT = ProjectContext(url="projects/bucket/My%20Project")
_ARTIFACTS = "projects/bucket/My%20Project/files/artifacts/"


def _make_resolver(
    *,
    dial_client: MagicMock | None = None,
    file_promoter: MagicMock | None = None,
    base_url: str = "https://dial.example",
    project: ProjectContext | None = None,
) -> AttachmentResolver:
    if dial_client is None:
        dial_client = MagicMock()
        dial_client.metadata.get = AsyncMock()
    if file_promoter is None:
        file_promoter = MagicMock(spec=DialFilePromoter)
        file_promoter.promote = AsyncMock()
    dial_settings = MagicMock(url=base_url)
    home_resolver = HomePathResolver(make_service(), make_config(), project)
    return AttachmentResolver(
        dial_client=dial_client,
        dial_settings=dial_settings,
        file_promoter=file_promoter,
        home_resolver=home_resolver,
        project=project,
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
async def test_unsupported_scheme_error_uses_stripped_value_for_data_uri_collapse():
    """The rejection error must be built from the already-stripped `bare` value, not the raw
    `file:...::` reference — otherwise a `file:`-wrapped `data:` URI's base64 payload isn't
    recognized/collapsed by sanitize_url and leaks raw payload bytes into the
    model-facing message."""
    resolver = _make_resolver()
    payload = "A" * 500
    file_relative_url = f"file:data::data:image/png;base64,{payload}"

    with pytest.raises(InvalidToolCallParameterException) as excinfo:
        await resolver._resolve_attachment(file_relative_url, supports_url_attachments=False)

    message = excinfo.value.message
    assert "data:image/png;base64,…" in message
    assert payload not in message


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


class TestProjectChat:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "projects/bucket/My%20Project/files/context/My%20Report.pdf",
            "projects/bucket/My Project/files/context/My Report.pdf",
            "file:url::projects/bucket/My%20Project/files/context/My%20Report.pdf",
            "https://dial.example/v1/projects/bucket/My%20Project/files/context/My%20Report.pdf",
        ],
    )
    async def test_current_project_url_passes_through_without_metadata(self, url: str):
        resolver = _make_resolver(project=_PROJECT)
        result = await resolver._resolve_attachment(url, supports_url_attachments=False)

        assert result == AttachmentParam(
            type="application/pdf",
            title="My Report.pdf",
            url="projects/bucket/My%20Project/files/context/My%20Report.pdf",
        )

    @pytest.mark.asyncio
    async def test_home_relative_path_resolves_under_artifacts(self):
        dial_client = MagicMock()
        dial_client.metadata.get = AsyncMock()
        resolver = _make_resolver(dial_client=dial_client, project=_PROJECT)

        result = await resolver._resolve_attachment("report.pdf", supports_url_attachments=False)

        assert result == AttachmentParam(
            type="application/pdf", title="report.pdf", url=f"{_ARTIFACTS}report.pdf"
        )
        dial_client.metadata.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_files_url_in_project_keeps_v1_metadata(self):
        fileinfo = MagicMock(content_type="image/png", url="files/b/x.png")
        fileinfo.name = "x.png"
        dial_client = MagicMock()
        dial_client.metadata.get = AsyncMock(return_value=fileinfo)
        resolver = _make_resolver(dial_client=dial_client, project=_PROJECT)

        result = await resolver._resolve_attachment("files/b/x.png", supports_url_attachments=False)

        dial_client.metadata.get.assert_awaited_once_with("files", "files/b/x.png")
        assert result["url"] == "files/b/x.png"

    @pytest.mark.asyncio
    async def test_other_project_url_is_rejected(self):
        """Only the current project's URLs resolve (D8)."""
        resolver = _make_resolver(project=_PROJECT)
        with pytest.raises(InvalidToolCallParameterException, match="current project"):
            await resolver._resolve_attachment(
                "projects/other/P/files/a.pdf", supports_url_attachments=False
            )

    @pytest.mark.asyncio
    async def test_project_url_without_project_is_rejected(self):
        resolver = _make_resolver()
        with pytest.raises(InvalidToolCallParameterException, match="current project"):
            await resolver._resolve_attachment(
                "projects/other/P/files/a.pdf", supports_url_attachments=False
            )

    @pytest.mark.asyncio
    async def test_without_project_home_relative_stays_unsupported(self):
        resolver = _make_resolver()
        with pytest.raises(InvalidToolCallParameterException):
            await resolver._resolve_attachment("notes.md", supports_url_attachments=False)
