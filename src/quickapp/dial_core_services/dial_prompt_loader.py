import logging

from aidial_client import AsyncDial, DialException, InvalidDialURLError, NotDialURLError
from injector import inject

from quickapp.common.url_sanitization import sanitize_url
from quickapp.dial_core_services.exceptions import DialPromptLoadError

logger = logging.getLogger(__name__)


@inject
class DialPromptLoader:
    """Loads prompt content from DIAL Core's prompts API."""

    def __init__(self, dial_client: AsyncDial) -> None:
        self._dial_client = dial_client

    async def load(self, path: str) -> str:
        """Return the prompt's content. Raises ``DialPromptLoadError`` on failure or empty content."""
        safe_path = sanitize_url(path)
        try:
            prompt = await self._dial_client.prompts.get(path)
        except DialException as e:
            logger.warning(
                "Failed to load DIAL prompt: path=%s, error=%s, status=%s",
                safe_path,
                type(e).__name__,
                e.status_code,
            )
            if isinstance(e, (InvalidDialURLError, NotDialURLError)):
                raise DialPromptLoadError(
                    "Invalid DIAL prompt path, expected prompts/<bucket>/<path>"
                ) from e
            raise DialPromptLoadError(
                f"DIAL prompt could not be loaded (status {e.status_code})"
            ) from e
        if prompt.content is None or not prompt.content.strip():
            logger.warning("DIAL prompt is empty: path=%s", safe_path)
            raise DialPromptLoadError("DIAL prompt has no content")
        logger.debug("Loaded DIAL prompt: path=%s, length=%d", safe_path, len(prompt.content))
        return prompt.content
