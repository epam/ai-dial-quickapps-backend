"""Validation of IANA time zone names coming from clients, models and app configs."""

from functools import cache
from importlib import resources

# In the tzdata list but not a real location: renders as "-00" with no offset rules.
_EXCLUDED_ZONES = frozenset({"Factory"})


@cache
def _known_zones() -> frozenset[str]:
    # The tzdata package list, not zoneinfo.available_timezones(): the latter also walks
    # the system TZPATH, so the result differs between images and can include `localtime`.
    names = resources.files("tzdata").joinpath("zones").read_text(encoding="utf-8").split()
    return frozenset(names) - _EXCLUDED_ZONES


def normalize_timezone_name(value: str | None) -> str | None:
    """Strip surrounding whitespace; an empty value means no zone was given."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def is_valid_iana_timezone(name: str) -> bool:
    """Exact, case-sensitive check against the shipped IANA zone list (aliases included).

    Use this instead of ``ZoneInfo(name)`` for untrusted input: ``ZoneInfo`` probes the
    filesystem with the raw string, so it accepts ``europe/warsaw`` on case-insensitive
    filesystems and resolves ``localtime`` to the server's own zone.
    """
    return name in _known_zones()
