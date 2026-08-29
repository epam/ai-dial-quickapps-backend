import logging

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider, singleton

from quickapp.common import StagedBaseTool
from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.exceptions import InitializationException
from quickapp.skills._inject_file_transfer_instruction_transformer import (
    _InjectFileTransferInstructionTransformer,
)
from quickapp.skills._predefined_skill import _PredefinedSkill
from quickapp.skills._settings import SkillsSettings
from quickapp.skills._skill import Skill
from quickapp.skills._skill_reader_tool import _SkillReaderTool
from quickapp.skills._skills_context import _SkillsContext
from quickapp.skills._skills_registry import SkillsRegistry
from quickapp.skills._tool_configs import SKILL_READER_TOOL_CONFIG, SKILL_READER_TOOL_NAME
from quickapp.skills.agent_skills_provider import AgentSkillsProvider

logger = logging.getLogger(__name__)


class SkillsModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(SkillsSettings, to=SkillsSettings, scope=singleton)
        binder.bind(AgentSkillsProvider, to=AgentSkillsProvider, scope=singleton)
        binder.bind(_SkillsContext, to=_SkillsContext, scope=request_scope)
        binder.bind(SkillsRegistry, to=SkillsRegistry, scope=request_scope)
        binder.bind(_SkillReaderTool, to=_SkillReaderTool, scope=request_scope)
        binder.bind(
            _InjectFileTransferInstructionTransformer,
            to=_InjectFileTransferInstructionTransformer,
            scope=request_scope,
        )

    @multiprovider
    def _provide_predefined_skills(self, provider: AgentSkillsProvider) -> list[Skill]:
        """Contribute the predefined skills to the source-neutral ``list[Skill]``.

        Each source package contributes through its own multiprovider, so
        ``SkillsRegistry`` owns precedence over whatever sources happen to be
        installed — a source that is absent, or gated off behind
        ``ENABLE_PREVIEW_FEATURES``, simply contributes nothing.
        """
        return [
            _PredefinedSkill(metadata=metadata, provider=provider)
            for metadata in provider.get_all_skills()
        ]

    @multiprovider
    def _provide_initialization_exceptions(
        self, context: _SkillsContext
    ) -> list[InitializationException]:
        return context.exceptions

    @multiprovider
    def _provide_internal_tools(
        self,
        skill_reader_builder: AssistedBuilder[_SkillReaderTool],
    ) -> list[StagedBaseTool]:
        return [
            skill_reader_builder.build(
                tool_config=SKILL_READER_TOOL_CONFIG,
                name=SKILL_READER_TOOL_NAME,
                description=SKILL_READER_TOOL_CONFIG.open_ai_tool.function.description,
            )
        ]

    @multiprovider
    def _provide_prompt_parts(
        self,
        skills_registry: SkillsRegistry,
    ) -> list[PromptPartProvider]:
        return [skills_registry]

    @multiprovider
    def _provide_message_transformers(
        self,
        file_transfer_transformer: _InjectFileTransferInstructionTransformer,
    ) -> list[MessagesTransformer]:
        return [file_transfer_transformer]
