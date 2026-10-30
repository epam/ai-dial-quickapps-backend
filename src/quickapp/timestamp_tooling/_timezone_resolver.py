import logging
from zoneinfo import ZoneInfo

from quickapp.common import TIMEZONE_HEADER
from quickapp.common.iana_timezones import parse_timezone
from quickapp.common.time_provider import TimezoneLabel

logger = logging.getLogger(__name__)

_UTC = ZoneInfo("UTC")


def resolve_user_timezone(header_value: str | None) -> tuple[ZoneInfo, TimezoneLabel]:
    """Return the request's zone and its label: the header's zone when valid, UTC otherwise.

    An invalid header never fails the request; it is skipped like an absent one.
    """
    try:
        header_zone = parse_timezone(header_value)
    except ValueError:
        # Client-supplied value: log its size only (CODESTYLE §9).
        logger.debug(
            "Ignoring %s header: not a known IANA time zone (length=%d)",
            TIMEZONE_HEADER,
            len((header_value or "").strip()),
        )
        header_zone = None
    if header_zone is None:
        return _UTC, TimezoneLabel.FALLBACK
    return header_zone, TimezoneLabel.USER
