import asyncio
import ipaddress
import logging
import mimetypes
from email.message import Message
from hashlib import sha256
from typing import Literal

import httpx
from injector import inject
from pydantic import BaseModel, ConfigDict

from quickapp.common.external_fetch_settings import ExternalFetchSettings
from quickapp.common.external_url_fetch_policy_resolver import (
    DisabledReason,
    ExternalUrlFetchPolicyResolver,
)
from quickapp.common.file_loading_size_limit_resolver import FileLoadingSizeLimitResolver
from quickapp.common.tool_timeout_resolver import ToolTimeoutResolver
from quickapp.common.utils import filename_from_url_path

logger = logging.getLogger(__name__)


class FetchedBytes(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    data: bytes
    content_type: str | None = None
    filename: str


_FetchErrorReason = Literal["ssrf_block", "size_limit", "redirect_cap", "timeout", "transport"]


class ExternalFetchError(Exception):
    """Raised by ExternalUrlFetcher on a security-envelope violation or transport error."""

    def __init__(self, reason: _FetchErrorReason, url: str, detail: str = "") -> None:
        self.reason: _FetchErrorReason = reason
        self.url = url
        self.detail = detail
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        match self.reason:
            case "ssrf_block":
                base = (
                    f"External URL {self.url} resolves to a blocked address "
                    "(loopback, private, link-local, or cloud-metadata)."
                )
            case "size_limit":
                base = f"External URL {self.url} exceeds the configured file-size limit."
            case "redirect_cap":
                base = f"External URL {self.url} exceeded the configured redirect limit."
            case "timeout":
                base = f"External URL {self.url} timed out."
            case "transport":
                base = f"External URL {self.url} could not be fetched."
        return f"{base} {self.detail}".strip()


_DISABLED_DETAIL: dict[DisabledReason, str] = {
    "admin": "External URL fetching is disabled by operator policy (EXTERNAL_URL_FETCH_ENABLED).",
    "builder": (
        "External URL fetching is disabled by this app "
        "(features.external_url_fetch.enabled=false)."
    ),
    "admin_allowlist": (
        "External URL host is not in the operator allowlist (EXTERNAL_URL_FETCH_HOST_ALLOWLIST)."
    ),
    "builder_allowlist": (
        "External URL host is not in this app's allowlist "
        "(features.external_url_fetch.host_allowlist)."
    ),
}


class ExternalFetchDisabledError(Exception):
    """Raised when the egress gate or host allowlist denies a fetch.

    Raised before any DNS lookup or network egress for the on/off gate
    reasons (``admin``, ``builder``) and for the host-allowlist reasons
    (``admin_allowlist``, ``builder_allowlist``).
    """

    def __init__(self, reason: DisabledReason, url: str) -> None:
        self.reason: DisabledReason = reason
        self.url = url
        super().__init__(
            f"{_DISABLED_DETAIL[reason]} Upload the file to DIAL and pass `files/...` instead, "
            f"or use a deployment that supports url_attachments. URL: {url}"
        )


_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def _is_blocked_address(addr: str) -> bool:
    """Return True if the address is unsafe for external egress.

    Uses stdlib classification flags rather than a hand-curated CIDR list so
    most IANA-defined ranges (loopback, RFC1918, link-local, multicast,
    reserved/TEST-NET, unspecified) are inherited automatically. CGNAT
    (RFC 6598, ``100.64/10``) is not in stdlib ``is_private`` and is checked
    explicitly. IPv4-mapped IPv6 addresses are unwrapped to IPv4 first so
    ``[::ffff:127.0.0.1]`` does not bypass the loopback check. Unparseable
    addresses fail closed — ``_resolve_addresses`` only ever passes strings
    produced by ``getaddrinfo``, so an unexpected shape is treated as a
    guard violation rather than silently allowed through.
    """
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True

    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT_NETWORK:
        return True

    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _resolve_addresses(host: str) -> list[str]:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except OSError:
        return []
    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        addr = sockaddr[0]
        if isinstance(addr, str):
            addresses.append(addr)
    return addresses


class _SsrfGuardTransport(httpx.AsyncHTTPTransport):
    """Custom transport that SSRF-checks and allowlist-checks every redirect target.

    Two checks run on each hop (initial request and every redirect target):

    * **Host allowlist.** When a policy resolver is supplied, the target host is
      checked against the admin and per-app allowlists; a denial raises
      :class:`ExternalFetchDisabledError` with the matching reason.
    * **SSRF.** The target host is resolved via :func:`_resolve_addresses` and
      rejected if any returned address is in a blocked range (see
      :func:`_is_blocked_address`).

    **Scope and known limitation.** The SSRF half catches accidental egress and
    multi-answer DNS responses where any address is internal. It does **not**
    defend against active DNS rebinding: httpx re-resolves DNS at the TCP
    connect step after this check returns, so an authoritative DNS server
    that returns different answers between our resolution and httpx's can
    still steer the connection to a private IP. A resolver-pinning fix
    (one DNS resolution, pinned for the duration of the request) is tracked
    as a follow-up.
    """

    # TODO: pin the validated IP for the actual TCP connect to close the
    # DNS-rebinding gap. Implementation will likely require a custom
    # httpcore network backend or a scoped getaddrinfo override.

    def __init__(self, policy: ExternalUrlFetchPolicyResolver | None = None) -> None:
        super().__init__()
        self.__policy = policy

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if not host:
            raise ExternalFetchError(reason="ssrf_block", url=str(request.url), detail="empty host")
        if self.__policy is not None:
            host_reason = self.__policy.resolve_host(host)
            if host_reason != "allowed":
                raise ExternalFetchDisabledError(reason=host_reason, url=str(request.url))
        addresses = await _resolve_addresses(host)
        if not addresses:
            raise ExternalFetchError(
                reason="ssrf_block",
                url=str(request.url),
                detail=f"could not resolve host {host}",
            )
        for addr in addresses:
            if _is_blocked_address(addr):
                raise ExternalFetchError(
                    reason="ssrf_block",
                    url=str(request.url),
                    detail=f"resolved to blocked address {addr}",
                )
        return await super().handle_async_request(request)


def _parse_content_disposition_filename(header_value: str | None) -> str | None:
    if not header_value:
        return None
    msg = Message()
    msg["content-disposition"] = header_value
    name = msg.get_param("filename", header="content-disposition")
    if isinstance(name, tuple):
        name = name[2]
    if isinstance(name, str) and name:
        return name
    return None


def _placeholder_filename(url: str, content_type: str | None) -> str:
    digest = sha256(url.encode("utf-8")).hexdigest()[:16]
    extension = mimetypes.guess_extension(content_type) if content_type else None
    return f"external-{digest}{extension or ''}"


def _derive_filename(response: httpx.Response, original_url: str, content_type: str | None) -> str:
    cd = _parse_content_disposition_filename(response.headers.get("content-disposition"))
    if cd:
        return cd
    final_url = str(response.url) if response.url else original_url
    from_path = filename_from_url_path(final_url)
    if from_path:
        return from_path
    return _placeholder_filename(original_url, content_type)


@inject
class ExternalUrlFetcher:
    """Single egress point for external URL file loading.

    Every external fetch QuickApps performs for *file loading* goes through
    this fetcher: SSRF guard, size limit, redirect cap, timeouts, and explicit
    credential isolation. Other ad-hoc HTTP clients (REST tools, the
    interpreter HTTP client, interactive login) are out of scope.
    """

    def __init__(
        self,
        settings: ExternalFetchSettings,
        policy: ExternalUrlFetchPolicyResolver,
        size_limit: FileLoadingSizeLimitResolver,
        timeout_resolver: ToolTimeoutResolver,
    ) -> None:
        self.__settings = settings
        self.__policy = policy
        self.__size_limit = size_limit
        self.__timeout_resolver = timeout_resolver

    async def fetch(self, url: str) -> FetchedBytes:
        reason = self.__policy.resolve_reason()
        if reason != "allowed":
            raise ExternalFetchDisabledError(reason=reason, url=url)

        tool_timeout = self.__timeout_resolver.resolve()
        timeout = httpx.Timeout(
            connect=self.__settings.connect_timeout_seconds,
            read=tool_timeout,
            write=tool_timeout,
            pool=tool_timeout,
        )
        transport = _SsrfGuardTransport(policy=self.__policy)
        limit = self.__size_limit.resolve()

        async with httpx.AsyncClient(
            transport=transport,
            timeout=timeout,
            follow_redirects=True,
            max_redirects=self.__settings.max_redirects,
            headers={},
            auth=None,
        ) as client:
            try:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            declared = int(content_length)
                        except ValueError:
                            declared = -1
                        if declared > limit:
                            raise ExternalFetchError(
                                reason="size_limit",
                                url=url,
                                detail=f"declared size {declared} > limit {limit}",
                            )
                    buffer = bytearray()
                    async for chunk in response.aiter_bytes():
                        buffer.extend(chunk)
                        if len(buffer) > limit:
                            raise ExternalFetchError(
                                reason="size_limit",
                                url=url,
                                detail=f"streamed bytes exceeded limit {limit}",
                            )
                    content_type = response.headers.get("content-type")
                    filename = _derive_filename(response, url, content_type)
                    return FetchedBytes(
                        data=bytes(buffer),
                        content_type=content_type,
                        filename=filename,
                    )
            except (ExternalFetchError, ExternalFetchDisabledError):
                raise
            except httpx.TooManyRedirects as exc:
                raise ExternalFetchError(reason="redirect_cap", url=url, detail=str(exc)) from exc
            except httpx.TimeoutException as exc:
                raise ExternalFetchError(reason="timeout", url=url, detail=str(exc)) from exc
            except httpx.HTTPError as exc:
                logger.debug("External fetch failed for %s", url, exc_info=True)
                raise ExternalFetchError(reason="transport", url=url, detail=str(exc)) from exc
