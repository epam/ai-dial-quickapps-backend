import logging

from injector import inject

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.shared.file_transfer import FileSource
from quickapp.skills.registry import SkillsRegistry
from quickapp.skills.skill_file_url import is_skill_reference, parse_skill_reference

logger = logging.getLogger(__name__)

MALFORMED_REFERENCE_MESSAGE = (
    "Malformed skill file reference. Expected skill://<skill_name>/<file_path>,"
    " as listed in the skill's <skill_files> block."
)


@inject
class _SkillFileSource(FileSource):
    """Serves ``skill://<name>/<path>`` references as the UTF-8 bytes of the skill file.

    The file is read through the skill's own reader, so the inventory check, the size
    cap and the per-request cache apply unchanged.
    """

    def __init__(self, registry: SkillsRegistry) -> None:
        self._registry = registry

    def handles(self, url: str) -> bool:
        return is_skill_reference(url)

    async def load(self, url: str, parameter_name: str) -> bytes:
        parsed = parse_skill_reference(url)
        if parsed is None:
            raise InvalidToolCallParameterException(
                parameter_name=parameter_name, message=MALFORMED_REFERENCE_MESSAGE
            )
        skill_name, file_path = parsed
        try:
            text = await self._registry.read_skill_file(skill_name, file_path)
        except Exception as exc:
            # The messages of these errors are written for the model and name the reason.
            logger.warning("Skill file could not be loaded for parameter %s", parameter_name)
            raise InvalidToolCallParameterException(
                parameter_name=parameter_name, message=str(exc)
            ) from exc
        return text.encode("utf-8")
