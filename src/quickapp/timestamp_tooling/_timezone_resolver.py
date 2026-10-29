import logging
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from quickapp.common import TIMEZONE_HEADER
from quickapp.common.iana_timezones import is_valid_iana_timezone, normalize_timezone_name
from quickapp.common.message_metadata import TimestampSource
from quickapp.common.time_provider import TimezoneLabel

logger = logging.getLogger(__name__)

_UTC = ZoneInfo("UTC")


class ResolvedTimezone(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    tz: ZoneInfo
    source: TimestampSource
    label: TimezoneLabel


def resolve_user_timezone(
    header_value: str | None, default_timezone: str | None
) -> ResolvedTimezone:
    """Pick the request's zone: valid header, then the app default, then UTC.

    An invalid header never fails the request; it is skipped like an absent one.
    """
    header_zone = normalize_timezone_name(header_value)
    if header_zone is not None:
        if is_valid_iana_timezone(header_zone):
            return ResolvedTimezone(
                tz=ZoneInfo(header_zone), source=TimestampSource.REQUEST, label=TimezoneLabel.USER
            )
        # Client-supplied value: log its size only (CODESTYLE §9).
        logger.debug(
            "Ignoring %s header: not a known IANA time zone (length=%d)",
            TIMEZONE_HEADER,
            len(header_zone),
        )

    if default_timezone is not None:
        return ResolvedTimezone(
            tz=ZoneInfo(default_timezone),
            source=TimestampSource.DEFAULT,
            label=TimezoneLabel.APP_DEFAULT,
        )
    return ResolvedTimezone(tz=_UTC, source=TimestampSource.DEFAULT, label=TimezoneLabel.FALLBACK)
