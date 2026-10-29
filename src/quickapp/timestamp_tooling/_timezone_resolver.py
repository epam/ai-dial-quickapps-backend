import logging
from zoneinfo import ZoneInfo

from quickapp.common import TIMEZONE_HEADER
from quickapp.common.iana_timezones import is_valid_iana_timezone, normalize_timezone_name
from quickapp.common.time_provider import TimezoneLabel

logger = logging.getLogger(__name__)

_UTC = ZoneInfo("UTC")


def resolve_user_timezone(header_value: str | None) -> tuple[ZoneInfo, TimezoneLabel]:
    """Return the request's zone and its label: the header's zone when valid, UTC otherwise.

    An invalid header never fails the request; it is skipped like an absent one.
    """
    header_zone = normalize_timezone_name(header_value)
    if header_zone is not None:
        if is_valid_iana_timezone(header_zone):
            return ZoneInfo(header_zone), TimezoneLabel.USER
        # Client-supplied value: log its size only (CODESTYLE §9).
        logger.debug(
            "Ignoring %s header: not a known IANA time zone (length=%d)",
            TIMEZONE_HEADER,
            len(header_zone),
        )
    return _UTC, TimezoneLabel.FALLBACK
