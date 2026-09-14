import logging
from typing import Any

from aidial_sdk.chat_completion import Message, Role

from quickapp.skills import SKILL_CHIPS_FIELD

logger = logging.getLogger(__name__)


def message_skill_urls(message: Message) -> list[str]:
    """Canonical skill URLs picked on one user message, in chip order, deduplicated.

    ``custom_content.skills`` on a non-user message is ignored. A malformed entry
    is dropped with a debug log — Core answers such a request with ``400``, so
    reaching here means something upstream changed, and refusing the turn over it
    would be worse.
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


def collect_skill_urls(messages: list[Message], max_skills: int) -> list[str]:
    """Every skill URL picked in the conversation, oldest first, capped.

    A URL keeps the position of its *latest* occurrence, so the cap drops the
    oldest picks and the chips of the message being answered survive it.
    """
    ordered: list[str] = []
    for message in messages:
        for url in message_skill_urls(message):
            if url in ordered:
                ordered.remove(url)
            ordered.append(url)
    return ordered[-max_skills:]


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
