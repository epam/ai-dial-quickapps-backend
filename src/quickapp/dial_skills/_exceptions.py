from quickapp.skills._exceptions import SkillFileError, SkillFileNotFound


class SkillNotFound(SkillFileNotFound):
    """DIAL Core answered 404 for the skill or one of its files.

    A ``SkillFileNotFound`` so a miss at *read* time renders like any other
    missing file, listing what the skill does contain.
    """


class SkillAccessDenied(SkillFileError):
    """DIAL Core answered 403.

    Usually means the skill was never auto-shared to the app's per-request key
    — the referenced-resource collector does not yet accept ``skills/`` URLs.
    """


class SkillClientError(SkillFileError):
    """Any other failure talking to DIAL Core's ``/v2/skills`` API."""
