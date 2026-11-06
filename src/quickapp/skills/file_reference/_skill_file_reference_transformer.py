import logging
from typing import Any

from injector import inject

from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.file_reference_pattern import FILE_PATTERN
from quickapp.skills.file_reference._skill_file_source import MALFORMED_REFERENCE_MESSAGE
from quickapp.skills.registry import SkillsRegistry
from quickapp.skills.skill_file_url import is_skill_reference, parse_skill_reference

logger = logging.getLogger(__name__)


@inject
class _SkillFileReferenceTransformer(ToolArgumentTransformer):
    """Rewrites ``skill://<name>/<path>`` (bare, or behind ``file:url::``) to the skill file's
    DIAL URL.

    Other prefixes (``text``, ``base64``, ``data``) are left to the file transformer, which
    loads the content through the skill file source. Matching is on the whole value, so
    prose that merely mentions a reference is never rewritten.
    """

    def __init__(self, registry: SkillsRegistry) -> None:
        self._registry = registry

    async def transform(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        for key, value in list(kwargs.items()):
            if isinstance(value, str):
                kwargs[key] = self._rewrite(key, value)
            elif isinstance(value, list):
                kwargs[key] = [
                    self._rewrite(key, elem) if isinstance(elem, str) else elem for elem in value
                ]
        return kwargs

    def _rewrite(self, key: str, value: str) -> str:
        reference = self._extract_reference(value)
        if reference is None:
            return value

        parsed = parse_skill_reference(reference)
        if parsed is None:
            raise InvalidToolCallParameterException(
                parameter_name=key, message=MALFORMED_REFERENCE_MESSAGE
            )
        try:
            url = self._registry.resolve_file_url(*parsed)
        except FileNotFoundError as exc:
            raise InvalidToolCallParameterException(parameter_name=key, message=str(exc)) from exc
        logger.debug("Skill file reference resolved for key %s", key)
        return url

    @staticmethod
    def _extract_reference(value: str) -> str | None:
        # A reference is a single line. Text inlined by `file:text::` can start with
        # `skill://` and must not be read back as a reference, whatever the chain order.
        if any(ord(ch) < 0x20 for ch in value):
            return None
        match = FILE_PATTERN.match(value)
        if match is None:
            return value if is_skill_reference(value) else None
        if (match.group("prefix") or "").lower() != "url":
            return None
        file_url = match.group("file_url")
        return file_url if is_skill_reference(file_url) else None
