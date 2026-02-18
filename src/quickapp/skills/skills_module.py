import logging

from fastapi_injector import request_scope
from injector import Binder, Module, ProviderOf, multiprovider, singleton, AssistedBuilder

from quickapp.common import StagedBaseTool
from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.base_initializer import StartupInitializer
from quickapp.skills.skills_initializer import _SkillsInitializer
from quickapp.skills._skill_reader_tool import _SkillReaderTool
from quickapp.skills._inject_file_transfer_instruction_transformer import (
    _InjectFileTransferInstructionTransformer,
)
from quickapp.skills._tool_configs import SKILL_READER_TOOL_CONFIG, SKILL_READER_TOOL_NAME
from quickapp.skills.agent_skills_provider import AgentSkillsProvider

logger = logging.getLogger(__name__)


class SkillsModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(AgentSkillsProvider, to=AgentSkillsProvider, scope=singleton)
        binder.bind(_SkillReaderTool, to=_SkillReaderTool, scope=request_scope)
        binder.bind(
            _InjectFileTransferInstructionTransformer,
            to=_InjectFileTransferInstructionTransformer,
            scope=request_scope,
        )

    @multiprovider
    def __provide_initializers(
        self, initializer_provider: ProviderOf[_SkillsInitializer]
    ) -> list[StartupInitializer]:
        return [initializer_provider.get()]

    @multiprovider
    def _provide_internal_tools(
        self,
        skill_reader_builder: AssistedBuilder[_SkillReaderTool],
    ) -> list[StagedBaseTool]:
        return [skill_reader_builder.build(
            tool_config=SKILL_READER_TOOL_CONFIG,
            name=SKILL_READER_TOOL_NAME,
            description=SKILL_READER_TOOL_CONFIG.open_ai_tool.function.description,
        )]

    @multiprovider
    def _provide_prompt_parts(
        self,
        skills_provider: AgentSkillsProvider,
    ) -> list[PromptPartProvider]:
        return [skills_provider]

    @multiprovider
    def _provide_message_transformers(
        self,
        file_transfer_transformer: _InjectFileTransferInstructionTransformer,
    ) -> list[MessagesTransformer]:
        return [file_transfer_transformer]

