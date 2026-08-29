import logging
from typing import Any

from injector import AssistedBuilder, inject

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.media_types import MediaTypes
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.skill_files import SKILL_MANIFEST_FILENAME
from quickapp.config.application import StageDisplayLevel
from quickapp.config.tools.internal import InternalTool
from quickapp.skills._exceptions import SkillFileError, SkillFileNotFound
from quickapp.skills._file_paths import normalize_skill_file_path
from quickapp.skills._settings import SkillsSettings
from quickapp.skills._skill import Skill
from quickapp.skills._skill_reader_stage_wrapper import _SkillReaderStageWrapper
from quickapp.skills._skills_registry import SkillsRegistry
from quickapp.skills._xml import generate_skill_files_xml

logger = logging.getLogger(__name__)


@inject
class _SkillReaderTool(StagedBaseTool):
    """Internal tool that reads skill content and returns it.

    Two modes behind one tool: without ``file_path`` it returns the manifest
    plus the skill's file inventory; with one it returns that bundled file.
    """

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_SkillReaderStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        skills_registry: SkillsRegistry,
        settings: SkillsSettings,
        stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            stage_display_level=stage_display_level,
            argument_transformers=argument_transformers,
            **kwargs,
        )
        self.__skills_registry = skills_registry
        self.__settings = settings

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        tool_call_id: str | None = None,
        skill_name: str | None = None,
        file_path: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        """Execute the skill reader tool."""
        if not skill_name:
            return self.__respond(stage_wrapper, "Missing required parameter: skill_name")

        try:
            requested = self.__resolve_requested_file(file_path)
            skill = self.__skills_registry.get_skill(skill_name)
        except SkillFileNotFound as e:
            logger.warning("Rejected read_skill call for skill '%s'", skill_name)
            return self.__respond(stage_wrapper, f"Error: {e}")

        try:
            if requested is None:
                return self.__respond(
                    stage_wrapper,
                    self.__read_manifest(skill),
                    content_type=MediaTypes.MARKDOWN,
                )

            content = await skill.read_file(requested)
            return self.__respond(stage_wrapper, content.text, content_type=content.content_type)
        except SkillFileNotFound as e:
            logger.warning("Skill '%s': requested file not found", skill_name)
            return self.__respond(stage_wrapper, f"Error: {e}{self.__available_files_hint(skill)}")
        except SkillFileError as e:
            logger.warning("Skill '%s' read failed: %s", skill_name, type(e).__name__)
            return self.__respond(stage_wrapper, f"Error: {e}")
        except Exception as e:
            logger.exception("Unexpected failure reading a file of skill '%s'", skill_name)
            return self.__respond(stage_wrapper, f"Error reading skill file: {e}")

    @staticmethod
    def __resolve_requested_file(file_path: str | None) -> str | None:
        """Return the normalized bundled path, or ``None`` for a manifest read.

        ``SKILL.md`` is accepted and means the same as omitting the parameter,
        so the model does not have to learn which spelling to use.
        """
        if file_path is None or not file_path.strip():
            return None
        normalized = normalize_skill_file_path(file_path)
        return None if normalized == SKILL_MANIFEST_FILENAME else normalized

    def __read_manifest(self, skill: Skill) -> str:
        manifest = skill.read_manifest()
        # Whatever the manifest did not spend of the file budget is what the
        # inventory may use, so the two together stay inside the cap the manifest
        # alone was measured against.
        remaining = self.__settings.file_max_bytes - len(manifest.encode("utf-8"))
        inventory = generate_skill_files_xml(
            skill.list_files(),
            skill.inventory_truncated,
            max_bytes=max(remaining, 0),
        )
        return f"{manifest}\n\n{inventory}" if inventory else manifest

    @staticmethod
    def __available_files_hint(skill: Skill) -> str:
        """List what the skill does contain, so the model can self-correct in one turn."""
        entries = skill.list_files()
        if not entries:
            return ""
        listing = "\n".join(entry.path for entry in entries)
        suffix = (
            "\n(this list is truncated; the skill has more files)"
            if skill.inventory_truncated
            else ""
        )
        return f"\nFiles bundled in this skill:\n{listing}{suffix}"

    @staticmethod
    def __respond(
        stage_wrapper: BaseStageWrapper | None,
        content: str,
        content_type: str = MediaTypes.PLAIN_TEXT,
    ) -> ToolCallResult:
        result = ToolCallResult(content=content, content_type=content_type)
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
