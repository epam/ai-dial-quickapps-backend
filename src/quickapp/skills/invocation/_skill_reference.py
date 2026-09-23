import logging
from typing import Any

from aidial_sdk.chat_completion import Message, Role
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

SKILL_CHIPS_FIELD = "skills"
"""Name of the ``custom_content`` field a client uses to invoke a skill."""


def message_skill_urls(message: Message) -> list[str]:
    """Canonical skill URLs picked on one user message, in chip order, deduplicated.

    ``custom_content.skills`` on a non-user message is ignored. A malformed entry is
    dropped with a debug log — Core answers such a request with ``400``, so reaching
    here means something upstream changed, and refusing the turn over it would be worse.
    """
    if message.role != Role.USER or message.custom_content is None:
        return []

    entries = (message.custom_content.model_extra or {}).get(SKILL_CHIPS_FIELD)
    if not isinstance(entries, list):
        if entries is not None:
            logger.debug("Ignoring a malformed custom_content.%s field", SKILL_CHIPS_FIELD)
        return []

    urls: list[str] = []
    for entry in entries:
        url = _canonical_url(entry)
        if url is None:
            logger.debug("Ignoring a malformed skill reference")
        elif url not in urls:
            urls.append(url)
    return urls


class ConversationPicks(BaseModel):
    """What the chips of a whole conversation add up to."""

    model_config = ConfigDict(frozen=True)

    by_ordinal: dict[int, list[str]] = Field(default_factory=dict)
    """Picked URLs, keyed by the ordinal of the user message that picked them, in
    chip order."""

    overflow_by_ordinal: dict[int, list[str]] = Field(default_factory=dict)
    """Extra URLs dropped because a message carried more chips than
    ``max_per_message``."""


def collect_picks(messages: list[Message], max_per_message: int) -> ConversationPicks:
    """Every skill pick in the conversation, keyed by the **ordinal** of the user
    message that made it (0 for the first user message, 1 for the second, ...).

    The ordinal is the anchor rather than a list index because the injector sees a
    different list from the one parsed here: ``extract_tool_calls`` has expanded the
    stored tool history and the scrub transformer has copied the chipped messages.
    User messages survive both, in order, so counting them is stable.

    Every distinct chip of a message is kept, up to ``max_per_message``; the rest are
    reported rather than dropped silently. A URL picked again on a later turn keeps
    its first pick, so the skill is loaded once, ahead of the message that first
    asked for it.
    """
    by_ordinal: dict[int, list[str]] = {}
    overflow_by_ordinal: dict[int, list[str]] = {}
    seen: set[str] = set()
    ordinal = -1

    for message in messages:
        if message.role != Role.USER:
            continue
        ordinal += 1
        urls = message_skill_urls(message)
        if not urls:
            continue

        kept, overflow = urls[:max_per_message], urls[max_per_message:]
        if overflow:
            overflow_by_ordinal[ordinal] = overflow
            # Debug, not warning: every turn re-parses the whole conversation, so a
            # warning here would repeat for every historical message that overflowed.
            logger.debug(
                "A user message carries more than %d skill chips; the rest are ignored",
                max_per_message,
            )

        fresh = [url for url in kept if url not in seen]
        seen.update(fresh)
        if fresh:
            by_ordinal[ordinal] = fresh

    return ConversationPicks(by_ordinal=by_ordinal, overflow_by_ordinal=overflow_by_ordinal)


def skill_name_from_url(url: str) -> str:
    """Last segment of a skill URL — what the manifest name would almost certainly
    have been, for a skill that failed to load and has no manifest to ask."""
    return url.rsplit("/", 1)[-1]


def _canonical_url(entry: Any) -> str | None:
    """``url`` of one chip without its trailing slash, or ``None`` if malformed.

    Core shares ``skills/<bucket>/<path>`` exactly as written and authorises every
    read of the skill against it, so the trailing slash has to go: a URL ending in
    ``/`` is shared under a different key and every read of it is then denied.
    """
    if not isinstance(entry, dict):
        return None
    url = entry.get("url")
    if not isinstance(url, str):
        return None
    return url.strip().rstrip("/") or None
