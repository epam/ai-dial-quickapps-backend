import mimetypes
from pathlib import PurePosixPath

from quickapp.common.media_types import MediaTypes

# `mimetypes` maps ".md" to "text/markdown" only on some platforms, and knows
# nothing about the extensions skill bundles actually use.
_EXTENSION_OVERRIDES: dict[str, str] = {
    ".md": MediaTypes.MARKDOWN,
    ".markdown": MediaTypes.MARKDOWN,
    ".txt": MediaTypes.PLAIN_TEXT,
    ".yaml": MediaTypes.PLAIN_TEXT,
    ".yml": MediaTypes.PLAIN_TEXT,
    ".json": MediaTypes.JSON,
    ".csv": MediaTypes.TEXT_CSV,
    ".py": MediaTypes.PLAIN_TEXT,
    ".sh": MediaTypes.PLAIN_TEXT,
    ".sql": MediaTypes.PLAIN_TEXT,
    ".toml": MediaTypes.PLAIN_TEXT,
}


def guess_skill_file_content_type(relative_path: str) -> str:
    """Best-effort content type for a bundled skill file, from its extension.

    Only ever labels text the agent is about to read — a file that does not
    decode as UTF-8 is refused before this matters.
    """
    suffix = PurePosixPath(relative_path).suffix.lower()
    if override := _EXTENSION_OVERRIDES.get(suffix):
        return override
    guessed, _ = mimetypes.guess_type(relative_path)
    return guessed or MediaTypes.PLAIN_TEXT
