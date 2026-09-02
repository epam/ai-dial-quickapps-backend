import logging

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider, singleton

from quickapp.common import StagedBaseTool
from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.skills._inject_file_transfer_instruction_transformer import (
    _InjectFileTransferInstructionTransformer,
)
from quickapp.skills._predefined_skills_source import _PredefinedSkillsSource
from quickapp.skills._skill_reader_tool import _SkillReaderTool
from quickapp.skills._skills_registry import SkillsRegistry
from quickapp.skills._tool_configs import SKILL_READER_TOOL_CONFIG, SKILL_READER_TOOL_NAME
from quickapp.skills.agent_skills_provider import AgentSkillsProvider
from quickapp.skills.skill_source import SkillSource

logger = logging.getLogger(__name__)


class SkillsModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(AgentSkillsProvider, to=AgentSkillsProvider, scope=singleton)
        binder.bind(_PredefinedSkillsSource, to=_PredefinedSkillsSource, scope=singleton)
        binder.bind(SkillsRegistry, to=SkillsRegistry, scope=request_scope)
        binder.bind(_SkillReaderTool, to=_SkillReaderTool, scope=request_scope)
        binder.bind(
            _InjectFileTransferInstructionTransformer,
            to=_InjectFileTransferInstructionTransformer,
            scope=request_scope,
        )

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
    def _provide_skill_sources(self, source: _PredefinedSkillsSource) -> list[SkillSource]:
        return [source]

    @multiprovider
    def _provide_message_transformers(
        self,
        file_transfer_transformer: _InjectFileTransferInstructionTransformer,
    ) -> list[MessagesTransformer]:
        return [file_transfer_transformer]
