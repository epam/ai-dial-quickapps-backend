from posixpath import normpath

from quickapp.skills._exceptions import SkillFileNotFound


def normalize_skill_file_path(relative_path: str) -> str:
    """Normalize a model-supplied path into a POSIX path relative to the skill root.

    The agent picks this string, so it is validated before it reaches any I/O:
    absolute paths, backslashes, and ``..`` segments are rejected outright
    rather than resolved. This is a *shape* check only — a symlink inside a
    skill could still point outside it, so any source reading from a local
    directory must also check containment on the resolved path.

    Raises:
        SkillFileNotFound: if the path is empty or not a relative path
            contained by the skill root.
    """
    candidate = relative_path.strip()
    if not candidate:
        raise SkillFileNotFound("An empty file path is not a file in this skill")
    if "\\" in candidate:
        raise SkillFileNotFound(
            f"'{relative_path}' uses backslashes; skill file paths are POSIX-style"
        )
    if candidate.startswith("/"):
        raise SkillFileNotFound(
            f"'{relative_path}' is an absolute path; give a path relative to the skill root"
        )
    if any(segment == ".." for segment in candidate.split("/")):
        raise SkillFileNotFound(
            f"'{relative_path}' escapes the skill root; '..' segments are not allowed"
        )

    # No `..` segment survived the check above, so `normpath` cannot produce a
    # parent reference here; "." is the only degenerate result left.
    normalized = normpath(candidate)
    if normalized == ".":
        raise SkillFileNotFound(f"'{relative_path}' is not a file in this skill")
    return normalized
