import logging
from urllib.parse import unquote

from aidial_client import AsyncDial, DialException, InvalidDialURLError, ResourceNotFoundError
from injector import inject

from quickapp.common.skill_files import SKILL_MANIFEST_FILENAME
from quickapp.common.url_sanitization import sanitize_url_for_log
from quickapp.dial_skills._exceptions import SkillAccessDenied, SkillClientError, SkillNotFound
from quickapp.skills._content_types import guess_skill_file_content_type
from quickapp.skills._exceptions import SkillFileNotText, SkillFileTooLarge
from quickapp.skills._settings import SkillsSettings
from quickapp.skills._skill import SkillFileContent, SkillFileEntry

logger = logging.getLogger(__name__)

# DIAL Core's ComplexResourceMetadataController caps `limit` at 1000.
_MAX_PAGE_SIZE = 1000

# A stuck or repeating `nextToken` would otherwise spin this loop forever:
# nothing above it imposes a deadline (`invoke_initializers` is a plain
# await loop and the client's timeout is per-request), so the whole chat
# request would hang inside initialization with no stage output.
_MAX_INVENTORY_PAGES = 50

_FORBIDDEN = 403


@inject
class DialSkillsClient:
    """Policy wrapper over ``aidial-client``'s ``skills`` resource.

    Transport is entirely the library's: URL parsing, the bucket/path split,
    percent-encoding, retries and the timeout policy all come from the
    injected ``AsyncDial``, which already carries this request's API key or
    bearer token and the resolved tool timeout. What this class adds is
    policy — mapping library exceptions onto QuickApps' skill exceptions,
    driving the inventory pagination loop against the configured cap, and
    keeping URLs out of the log unsanitized.

    The whole-resource ZIP endpoint is deliberately unused: it materialises
    every bundled file, binaries included, where two small requests at
    initialization plus one per file the agent actually opens is strictly
    cheaper.
    """

    def __init__(self, dial_client: AsyncDial, settings: SkillsSettings) -> None:
        self._client = dial_client
        self._settings = settings

    async def get_manifest(self, url: str) -> str:
        """Fetch a skill's ``SKILL.md``. Called once per skill at initialization."""
        return (await self.get_file(url, SKILL_MANIFEST_FILENAME)).text

    async def get_file(self, url: str, relative_path: str) -> SkillFileContent:
        """Fetch one file from a skill in a single Core round-trip.

        Raises:
            SkillNotFound / SkillAccessDenied / SkillClientError: Core said no.
            SkillFileTooLarge: over ``SKILLS_FILE_MAX_BYTES``.
            SkillFileNotText: not decodable as UTF-8.
        """
        try:
            # The `skills` resource exists at runtime but the pre-release
            # aidial-client does not expose it to mypy, so the ignores below go
            # away with the dependency bump.
            response = await self._client.skills.get_file(  # type: ignore[attr-defined]
                url, relative_path
            )
            raw = await response.aget_content()
        except Exception as exc:
            raise self._map_error(exc, url, relative_path) from exc

        if len(raw) > self._settings.file_max_bytes:
            raise SkillFileTooLarge(relative_path, len(raw), self._settings.file_max_bytes)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise SkillFileNotText(relative_path, len(raw))

        return SkillFileContent(
            path=relative_path,
            text=text,
            content_type=guess_skill_file_content_type(relative_path),
        )

    async def list_files(self, url: str) -> tuple[list[SkillFileEntry], bool]:
        """List a skill's bundled files. Returns ``(entries, truncated)``.

        The listing is paged and a page may hold fewer nodes than ``limit``, so
        the ``nextToken`` chain is followed to exhaustion rather than trusting
        a single call. For a DIAL skill the cap bounds what is *known*, not
        just what is shown — hence the truncation flag, which the reader tool
        needs so a "no such file" error cannot imply the skill holds nothing
        else.
        """
        cap = self._settings.inventory_max_entries
        entries: list[SkillFileEntry] = []
        seen_paths: set[str] = set()
        token: str | None = None
        seen_tokens: set[str] = set()

        for _ in range(_MAX_INVENTORY_PAGES):
            try:
                page = await self._client.skills.list_files(  # type: ignore[attr-defined]
                    url,
                    recursive=True,
                    limit=min(cap + 1, _MAX_PAGE_SIZE),
                    token=token,
                )
            except Exception as exc:
                raise self._map_error(exc, url) from exc

            prefix = page.url
            for item in page.items or []:
                # Directory nodes are not readable paths. Core's recursive
                # listing already drops non-blob entries; filtering here guards
                # the contract rather than an observed behavior.
                if item.url.endswith("/"):
                    continue
                relative = self._relative_path(item.url, prefix)
                if not relative or relative == SKILL_MANIFEST_FILENAME:
                    continue
                # A repeated cursor replays a page, and the same path listed
                # twice would be shown to the model twice and spend the cap
                # twice.
                if relative in seen_paths:
                    continue
                seen_paths.add(relative)
                entries.append(SkillFileEntry(path=relative))

            if len(entries) > cap:
                # WARNING, not INFO: the agent is about to be shown a partial
                # view of the skill. Matches the predefined side's level for the
                # same event.
                logger.warning(
                    "Skill inventory for %s truncated at %d entries",
                    sanitize_url_for_log(url),
                    cap,
                )
                return entries[:cap], True

            token = page.next_token
            if not token:
                return entries, False
            if token in seen_tokens:
                # Core handed back a cursor it already gave us; the next request
                # would be byte-identical. Stop and mark the view partial.
                logger.warning(
                    "Skill inventory listing for %s repeated a page token; stopping",
                    sanitize_url_for_log(url),
                )
                return entries, True
            seen_tokens.add(token)

        logger.warning(
            "Skill inventory listing for %s exceeded %d pages; stopping",
            sanitize_url_for_log(url),
            _MAX_INVENTORY_PAGES,
        )
        return entries, True

    @staticmethod
    def _relative_path(item_url: str, listing_url: str) -> str:
        """Turn a listed item's URL into a path relative to the skill root.

        Core builds every entry under ``{skill}/files/`` and percent-encodes
        each segment, so the listing folder's own URL is the prefix to drop and
        the remainder has to be decoded before it can be handed back to the
        library, which encodes what it is given.
        """
        if not item_url.startswith(listing_url):
            # `removeprefix` is a silent no-op on a mismatch, which would show
            # the model a full `skills/<bucket>/...` URL as if it were a path
            # inside the skill and 404 on every read.
            return ""
        remainder = item_url.removeprefix(listing_url).lstrip("/")
        return "/".join(unquote(segment) for segment in remainder.split("/"))

    @staticmethod
    def _map_error(exc: Exception, url: str, relative_path: str | None = None) -> Exception:
        """Map a library exception onto a skill exception.

        Library exceptions, never HTTP statuses: the client's
        ``_raise_for_status`` either applies the resource's error processor or
        falls back to a ``DialException`` carrying ``status_code``, so a raw
        ``httpx.HTTPStatusError`` never reaches this far.
        """
        safe_url = sanitize_url_for_log(url)
        where = f"{safe_url}/{relative_path}" if relative_path else safe_url

        if isinstance(exc, ResourceNotFoundError):
            return SkillNotFound(f"'{where}' was not found in DIAL")
        if isinstance(exc, InvalidDialURLError):
            # A path the library refuses to build a URL from is, from the
            # agent's side, simply not a file in this skill - and routing it to
            # SkillFileNotFound is what keeps the reader tool's "here is what the
            # skill does contain" hint in play.
            return SkillNotFound(f"'{where}' is not a valid path in this skill")
        if isinstance(exc, DialException):
            if exc.status_code == _FORBIDDEN:
                return SkillAccessDenied(
                    f"Access to '{where}' was denied. The skill may not be shared"
                    " with this application."
                )
            return SkillClientError(f"Failed to read '{where}' from DIAL: {exc.message}")
        # `str(exc)` is empty for exactly the failures most expected here -
        # `str(TimeoutError())` is "" - so lead with the type.
        detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        return SkillClientError(f"Failed to read '{where}' from DIAL: {detail}")
