import logging

from fastapi_injector import request_scope
from injector import Binder, Module, multiprovider

from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.file_transfer import FileSource
from quickapp.skills.file_reference._inject_skill_file_reference_instruction_transformer import (
    _InjectSkillFileReferenceInstructionTransformer,
)
from quickapp.skills.file_reference._skill_file_reference_transformer import (
    _SkillFileReferenceTransformer,
)
from quickapp.skills.file_reference._skill_file_source import _SkillFileSource

logger = logging.getLogger(__name__)


class SkillFileReferenceModule(Module):
    """Wires ``skill://<name>/<path>`` references: argument rewriting for URL delivery and a
    file source for content delivery (``text`` / ``base64`` / ``data``)."""

    def configure(self, binder: Binder) -> None:
        binder.bind(_SkillFileSource, to=_SkillFileSource, scope=request_scope)
        binder.bind(
            _SkillFileReferenceTransformer, to=_SkillFileReferenceTransformer, scope=request_scope
        )
        binder.bind(
            _InjectSkillFileReferenceInstructionTransformer,
            to=_InjectSkillFileReferenceInstructionTransformer,
            scope=request_scope,
        )

    @multiprovider
    def _provide_file_sources(self, source: _SkillFileSource) -> list[FileSource]:
        return [source]

    @multiprovider
    def _provide_argument_transformers(
        self, transformer: _SkillFileReferenceTransformer
    ) -> list[ToolArgumentTransformer]:
        return [transformer]

    @multiprovider
    def _provide_message_transformers(
        self, injector: _InjectSkillFileReferenceInstructionTransformer
    ) -> list[MessagesTransformer]:
        return [injector]
