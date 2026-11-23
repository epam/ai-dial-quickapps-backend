import re
from urllib.parse import quote, unquote

SKILL_REFERENCE_PREFIX = "skill://"

# Lazy root, so the first `/files/` after the bucket separates the skill root from the file path.
_SKILL_FILE_URL = re.compile(r"^(skills/[^/]+/.+?)/files/.+$")


def is_skill_reference(value: str) -> bool:
    return value.startswith(SKILL_REFERENCE_PREFIX)


def format_skill_reference(skill_name: str, file_path: str) -> str:
    return f"{SKILL_REFERENCE_PREFIX}{skill_name}/{file_path}"


def parse_skill_reference(value: str) -> tuple[str, str] | None:
    """Split ``skill://<name>/<path>`` into ``(name, path)``; ``None`` unless both are non-empty."""
    if not is_skill_reference(value):
        return None
    name, _, path = value[len(SKILL_REFERENCE_PREFIX) :].partition("/")
    if not name or not path:
        return None
    return name, path


def normalize_skill_file_path(file_path: str, skill_name: str) -> str:
    """Strip the decorations a model tends to add around a listed path.

    Only the skill's own ``skill://<name>/`` prefix is dropped; a reference to another
    skill stays as is and fails the inventory check.
    """
    return (
        file_path.strip()
        .removeprefix(f"{SKILL_REFERENCE_PREFIX}{skill_name}/")
        .lstrip("/")
        .removeprefix("./")
    )


def build_skill_file_url(skill_url: str, file_path: str) -> str:
    return f"{skill_url.rstrip('/')}/files/{quote(file_path, safe='/')}"


def skill_root_of_file_url(value: str) -> str | None:
    """The ``skills/<bucket>/<path>`` root when *value* is a skill file URL, else ``None``.

    Dot segments (also percent-encoded) disqualify the value, so a crafted path cannot
    borrow the grant issued for the root it claims.
    """
    match = _SKILL_FILE_URL.match(value)
    if match is None:
        return None
    if any(segment in (".", "..") for segment in unquote(value).split("/")):
        return None
    return match.group(1)
