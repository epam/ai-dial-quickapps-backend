from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from quickapp.common.file_loading_size_limit_resolver import FileLoadingSizeLimitResolver
from quickapp.shared.external_fetch._external_fetch_settings import ExternalFetchSettings
from quickapp.shared.external_fetch._external_url_fetch_policy_resolver import (
    ExternalUrlFetchPolicyResolver,
)
from quickapp.shared.external_fetch.external_url_fetcher import (
    ExternalFetchDisabledError,
    ExternalFetchError,
    ExternalUrlFetcher,
    FetchedBytes,
    _derive_filename,
    _placeholder_filename,
    _sanitize_external_filename,
    _SsrfGuardTransport,
)
from tests.unit_tests.common.common import noop_timeout_resolver


def _settings(allow_redirects: int = 5, connect: float = 5.0) -> MagicMock:
    s = MagicMock(spec=ExternalFetchSettings)
    s.max_redirects = allow_redirects
    s.connect_timeout_seconds = connect
    return s


def _policy(reason: str = "allowed", host_reason: str = "allowed") -> MagicMock:
    p = MagicMock(spec=ExternalUrlFetchPolicyResolver)
    p.resolve_reason.return_value = reason
    p.resolve_host.return_value = host_reason
    return p


def _size(limit: int = 1024) -> MagicMock:
    r = MagicMock(spec=FileLoadingSizeLimitResolver)
    r.resolve.return_value = limit
    return r


def _fetcher(
    settings: MagicMock | None = None,
    policy: MagicMock | None = None,
    size: MagicMock | None = None,
) -> ExternalUrlFetcher:
    return ExternalUrlFetcher(
        settings or _settings(),
        policy or _policy(),
        size or _size(),
        noop_timeout_resolver(),
    )


_RESOLVE_PATH = "quickapp.shared.external_fetch.external_url_fetcher._resolve_addresses"


def _patch_resolve(addresses: list[str]) -> AsyncMock:
    return AsyncMock(return_value=addresses)


@pytest.mark.asyncio
async def test_admin_disabled_raises_disabled_error_before_dns():
    policy = _policy(reason="admin")
    fetcher = _fetcher(policy=policy)
    resolve_mock = _patch_resolve([])
    with patch(_RESOLVE_PATH, new=resolve_mock):
        with pytest.raises(ExternalFetchDisabledError) as excinfo:
            await fetcher.fetch("https://example.com/x")
    assert excinfo.value.reason == "admin"
    resolve_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_builder_disabled_raises_disabled_error_with_builder_reason():
    policy = _policy(reason="builder")
    fetcher = _fetcher(policy=policy)
    with pytest.raises(ExternalFetchDisabledError) as excinfo:
        await fetcher.fetch("https://example.com/x")
    assert excinfo.value.reason == "builder"


@pytest.mark.asyncio
async def test_admin_allowlist_denial_raises_before_dns():
    policy = _policy(host_reason="admin_allowlist")
    fetcher = _fetcher(policy=policy)
    resolve_mock = _patch_resolve([])
    with patch(_RESOLVE_PATH, new=resolve_mock):
        with pytest.raises(ExternalFetchDisabledError) as excinfo:
            await fetcher.fetch("https://evil.com/x")
    assert excinfo.value.reason == "admin_allowlist"
    resolve_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_builder_allowlist_denial_raises_with_builder_allowlist_reason():
    policy = _policy(host_reason="builder_allowlist")
    fetcher = _fetcher(policy=policy)
    with pytest.raises(ExternalFetchDisabledError) as excinfo:
        await fetcher.fetch("https://evil.com/x")
    assert excinfo.value.reason == "builder_allowlist"


@pytest.mark.asyncio
async def test_transport_redirect_hop_runs_host_check():
    policy = _policy(host_reason="admin_allowlist")
    transport = _SsrfGuardTransport(policy=policy)
    request = httpx.Request("GET", "https://evil.com/redirect-target")
    with pytest.raises(ExternalFetchDisabledError) as excinfo:
        await transport.handle_async_request(request)
    assert excinfo.value.reason == "admin_allowlist"
    policy.resolve_host.assert_called_once_with("evil.com")


@pytest.mark.asyncio
async def test_no_dial_credentials_leak_to_external_host():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=b"ok", headers={"content-type": "text/plain"})

    mock_transport = httpx.MockTransport(handler)
    with patch(
        "quickapp.shared.external_fetch.external_url_fetcher._SsrfGuardTransport",
        return_value=mock_transport,
    ):
        await _fetcher(size=_size(1024)).fetch("https://example.com/file")

    assert len(captured) == 1
    sent_headers = {h.lower() for h in captured[0].headers.keys()}
    forbidden = {"authorization", "api-key", "x-forwarded-for", "x-real-ip"}
    leaked = forbidden & sent_headers
    assert not leaked, f"forbidden headers reached external host: {leaked}"


@pytest.mark.asyncio
async def test_happy_path_returns_fetched_bytes():
    fetcher = _fetcher(size=_size(1024))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"hello",
            headers={
                "content-type": "text/plain",
                "content-disposition": 'attachment; filename="hi.txt"',
            },
        )

    mock_transport = httpx.MockTransport(handler)
    with patch(
        "quickapp.shared.external_fetch.external_url_fetcher._SsrfGuardTransport",
        return_value=mock_transport,
    ):
        with patch(_RESOLVE_PATH, new=_patch_resolve(["8.8.8.8"])):
            result = await fetcher.fetch("https://example.com/file")

    assert isinstance(result, FetchedBytes)
    assert result.data == b"hello"
    assert result.content_type == "text/plain"
    assert result.filename == "hi.txt"


@pytest.mark.asyncio
async def test_size_limit_via_content_length_header():
    fetcher = _fetcher(size=_size(10))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"oversize body content",
            headers={"content-length": "100"},
        )

    mock_transport = httpx.MockTransport(handler)
    with patch(
        "quickapp.shared.external_fetch.external_url_fetcher._SsrfGuardTransport",
        return_value=mock_transport,
    ):
        with pytest.raises(ExternalFetchError) as excinfo:
            await fetcher.fetch("https://example.com/big")

    assert excinfo.value.reason == "size_limit"


@pytest.mark.asyncio
async def test_size_limit_via_streaming_when_no_content_length():
    fetcher = _fetcher(size=_size(5))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"oversize-mid-stream")

    mock_transport = httpx.MockTransport(handler)
    with patch(
        "quickapp.shared.external_fetch.external_url_fetcher._SsrfGuardTransport",
        return_value=mock_transport,
    ):
        with pytest.raises(ExternalFetchError) as excinfo:
            await fetcher.fetch("https://example.com/x")

    assert excinfo.value.reason == "size_limit"


@pytest.mark.asyncio
async def test_ssrf_block_when_host_resolves_to_loopback():
    transport = _SsrfGuardTransport()
    request = httpx.Request("GET", "https://internal.example/x")
    with patch(_RESOLVE_PATH, new=_patch_resolve(["127.0.0.1"])):
        with pytest.raises(ExternalFetchError) as excinfo:
            await transport.handle_async_request(request)
    assert excinfo.value.reason == "ssrf_block"


@pytest.mark.asyncio
async def test_ssrf_block_dns_rebinding_mixed_addresses():
    transport = _SsrfGuardTransport()
    request = httpx.Request("GET", "https://example.com/x")
    with patch(_RESOLVE_PATH, new=_patch_resolve(["8.8.8.8", "127.0.0.1"])):
        with pytest.raises(ExternalFetchError) as excinfo:
            await transport.handle_async_request(request)
    assert excinfo.value.reason == "ssrf_block"


@pytest.mark.asyncio
async def test_unresolvable_host_treated_as_ssrf_block():
    transport = _SsrfGuardTransport()
    request = httpx.Request("GET", "https://nope.invalid/x")
    with patch(_RESOLVE_PATH, new=_patch_resolve([])):
        with pytest.raises(ExternalFetchError) as excinfo:
            await transport.handle_async_request(request)
    assert excinfo.value.reason == "ssrf_block"


@pytest.mark.parametrize(
    "addr",
    [
        "0.0.0.0",
        "100.64.0.1",
        "192.0.2.1",
        "198.51.100.1",
        "203.0.113.1",
        "224.0.0.1",
        "fc00::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
    ],
)
@pytest.mark.asyncio
async def test_ssrf_block_for_extended_ranges(addr: str):
    transport = _SsrfGuardTransport()
    request = httpx.Request("GET", "https://anywhere.example/x")
    with patch(_RESOLVE_PATH, new=_patch_resolve([addr])):
        with pytest.raises(ExternalFetchError) as excinfo:
            await transport.handle_async_request(request)
    assert excinfo.value.reason == "ssrf_block"


@pytest.mark.asyncio
async def test_ssrf_block_when_address_unparseable():
    transport = _SsrfGuardTransport()
    request = httpx.Request("GET", "https://anywhere.example/x")
    with patch(_RESOLVE_PATH, new=_patch_resolve(["not-an-ip"])):
        with pytest.raises(ExternalFetchError) as excinfo:
            await transport.handle_async_request(request)
    assert excinfo.value.reason == "ssrf_block"


@pytest.mark.asyncio
async def test_redirect_cap_raises_redirect_cap_error():
    fetcher = _fetcher(settings=_settings(allow_redirects=1))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://example.com/next"})

    mock_transport = httpx.MockTransport(handler)
    with patch(
        "quickapp.shared.external_fetch.external_url_fetcher._SsrfGuardTransport",
        return_value=mock_transport,
    ):
        with pytest.raises(ExternalFetchError) as excinfo:
            await fetcher.fetch("https://example.com/start")

    assert excinfo.value.reason == "redirect_cap"


@pytest.mark.asyncio
async def test_timeout_raises_timeout_error():
    fetcher = _fetcher()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    mock_transport = httpx.MockTransport(handler)
    with patch(
        "quickapp.shared.external_fetch.external_url_fetcher._SsrfGuardTransport",
        return_value=mock_transport,
    ):
        with pytest.raises(ExternalFetchError) as excinfo:
            await fetcher.fetch("https://example.com/slow")

    assert excinfo.value.reason == "timeout"


@pytest.mark.asyncio
async def test_transport_error_maps_to_transport_reason():
    fetcher = _fetcher()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("conn refused")

    mock_transport = httpx.MockTransport(handler)
    with patch(
        "quickapp.shared.external_fetch.external_url_fetcher._SsrfGuardTransport",
        return_value=mock_transport,
    ):
        with pytest.raises(ExternalFetchError) as excinfo:
            await fetcher.fetch("https://example.com/x")

    assert excinfo.value.reason == "transport"


def test_filename_content_disposition_wins():
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com/from-path.bin"),
        headers={"content-disposition": 'attachment; filename="cd-name.txt"'},
    )
    assert _derive_filename(response, "https://example.com/x.bin", "text/plain") == "cd-name.txt"


def test_filename_falls_back_to_url_path():
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com/path/Foo%20bar.pdf"),
    )
    assert (
        _derive_filename(response, "https://example.com/x.bin", "application/pdf") == "Foo-bar.pdf"
    )


def test_filename_falls_back_to_hash_placeholder_when_path_empty():
    response = httpx.Response(200, request=httpx.Request("GET", "https://example.com/"))
    out = _derive_filename(response, "https://example.com/", "application/pdf")
    assert out.startswith("external-")
    assert out.endswith(".pdf")


def test_placeholder_filename_extension_falls_back_to_empty():
    out = _placeholder_filename("https://example.com/x", None)
    assert out.startswith("external-")
    assert not out.endswith(".")  # no trailing dot from a missing extension


def test_placeholder_filename_strips_content_type_parameters():
    # ``mimetypes.guess_extension`` returns ``None`` for parameterised types
    # like ``application/pdf; charset=binary``; strip parameters first so the
    # placeholder still gets a useful extension.
    out = _placeholder_filename("https://example.com/x", "application/pdf; charset=binary")
    assert out.endswith(".pdf")


def test_placeholder_filename_handles_whitespace_around_parameters():
    out = _placeholder_filename("https://example.com/x", "text/plain ; charset=utf-8")
    assert out.endswith(".txt")


class TestSanitizeExternalFilename:
    """Untrusted Content-Disposition / URL-path filenames feed straight into
    ``files/{bucket}/{filename}`` on upload; sanitisation must keep path
    components, control chars, and leading-dot escapes out of the upload URL."""

    def test_strips_posix_path_traversal(self):
        assert _sanitize_external_filename("../../poison.pdf") == "poison.pdf"

    def test_strips_windows_path_traversal(self):
        assert _sanitize_external_filename("..\\..\\poison.pdf") == "poison.pdf"

    def test_mixed_separator_takes_last_segment(self):
        assert _sanitize_external_filename("a/b\\c/d.pdf") == "d.pdf"

    def test_strips_c0_control_characters(self):
        # NUL, newline, carriage return, DEL.
        assert _sanitize_external_filename("foo\x00bar\nbaz\r\x7f.pdf") == "foobarbaz.pdf"

    def test_strips_c1_control_characters(self):
        # C1 controls (U+0080-U+009F) are not valid in a DIAL upload URL —
        # they would either be rejected at parse time or misrender downstream.
        assert _sanitize_external_filename("foo\x80bar\x9f.pdf") == "foobar.pdf"

    def test_preserves_legitimate_dotfiles(self):
        # Single-dot prefixes on real filenames are not traversal segments.
        assert _sanitize_external_filename(".bashrc") == ".bashrc"
        assert _sanitize_external_filename(".env") == ".env"
        assert _sanitize_external_filename(".gitignore") == ".gitignore"

    def test_preserves_multi_dot_prefixed_filenames(self):
        # ``...hidden.pdf`` is a weird name but not a traversal segment —
        # only standalone ``.`` and ``..`` are dangerous.
        assert _sanitize_external_filename("...hidden.pdf") == "...hidden.pdf"

    def test_dot_only_collapses_to_empty(self):
        assert _sanitize_external_filename("..") == ""
        assert _sanitize_external_filename(".") == ""
        assert _sanitize_external_filename("./") == ""
        assert _sanitize_external_filename("...") == ""

    def test_url_decoded_separators_in_content_disposition(self):
        # Plain ``filename="..."`` form does not percent-decode via
        # email.message — the sanitiser must decode itself or %2F survives
        # the segment split and lands in the bucket URL untouched.
        assert _sanitize_external_filename("..%2F..%2Fposion.pdf") == "posion.pdf"
        assert _sanitize_external_filename("..%5C..%5Cposion.pdf") == "posion.pdf"

    def test_trailing_slash_keeps_safe_filename(self):
        # Some servers quote a trailing slash by mistake; ``rsplit('/',1)[-1]``
        # on ``"document.pdf/"`` returns ``""`` without the rstrip.
        assert _sanitize_external_filename("document.pdf/") == "document.pdf"

    def test_whitespace_replaced_with_dash(self):
        assert _sanitize_external_filename("hello world.pdf") == "hello-world.pdf"

    def test_disallowed_shell_chars_replaced(self):
        # sanitize_filename swaps \\ / : * ? " < > | for '-' before the
        # leading-dot strip; the leading segment is already taken first.
        assert _sanitize_external_filename('a:b*c?d"e<f>g|h.pdf') == "a-b-c-d-e-f-g-h.pdf"

    def test_empty_input_returns_empty(self):
        assert _sanitize_external_filename("") == ""

    def test_only_separators_returns_empty(self):
        assert _sanitize_external_filename("///") == ""


def test_derive_filename_falls_back_to_placeholder_when_cd_sanitises_to_empty():
    """A malicious upstream Content-Disposition that's pure separators / dots
    must not produce an empty filename — we fall through to the URL path, and
    if that also sanitises empty, to the hash placeholder."""
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com/"),
        headers={"content-disposition": 'attachment; filename="../../.."'},
    )
    out = _derive_filename(response, "https://example.com/", "application/pdf")
    assert out.startswith("external-")
    assert out.endswith(".pdf")


def test_derive_filename_blocks_path_traversal_in_content_disposition():
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com/x"),
        headers={"content-disposition": 'attachment; filename="../../etc/passwd"'},
    )
    assert _derive_filename(response, "https://example.com/x", None) == "passwd"


def test_derive_filename_blocks_path_traversal_in_url_path():
    # Server redirects (or the original URL) carries a traversal payload in
    # the path; the response final URL is what feeds the path fallback.
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com/safe/..%2F..%2Fposion.pdf"),
    )
    # filename_from_url_path URL-decodes; the result starts with `..` which we
    # split off and discard.
    assert _derive_filename(response, "https://example.com/x", None) == "posion.pdf"
