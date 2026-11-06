import logging

from aidial_client import AsyncDial, DialException
from aidial_client._exception import InvalidDialURLError

from quickapp.common.url_sanitization import sanitize_url

logger = logging.getLogger(__name__)


class DialSystemPromptError(Exception):
    """A `dial` system prompt could not be loaded. The message is safe to show to users."""


async def fetch_dial_system_prompt(client: AsyncDial, path: str) -> str:
    """Fetch a `dial` system prompt. Raises ``DialSystemPromptError`` on failure or empty content."""
    safe_path = sanitize_url(path)
    try:
        prompt = await client.prompts.get(path)
    except DialException as e:
        logger.warning(
            "Failed to load DIAL system prompt: path=%s, error=%s, status=%s",
            safe_path,
            type(e).__name__,
            int(e.status_code),
        )
        if isinstance(e, InvalidDialURLError):
            raise DialSystemPromptError(
                "Invalid DIAL prompt path, expected prompts/<bucket>/<path>"
            ) from e
        raise DialSystemPromptError(
            f"DIAL prompt could not be loaded (status {int(e.status_code)})"
        ) from e
    if prompt.content is None or not prompt.content.strip():
        logger.warning("DIAL system prompt is empty: path=%s", safe_path)
        raise DialSystemPromptError("DIAL prompt has no content")
    logger.debug("Loaded DIAL system prompt: path=%s, length=%d", safe_path, len(prompt.content))
    return prompt.content
