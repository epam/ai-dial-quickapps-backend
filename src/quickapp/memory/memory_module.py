from fastapi_injector import request_scope
from injector import Binder, Module, multiprovider, provider, singleton

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.di_types import BUILTIN_SKILLS_TO_INJECT
from quickapp.common.preview import preview_module
from quickapp.memory._memory_settings import MemorySettings
from quickapp.memory._retrieve_memory_transformer import _RetrieveMemoryTransformer


@preview_module
class MemoryModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_RetrieveMemoryTransformer, to=_RetrieveMemoryTransformer, scope=request_scope)

    @singleton
    @provider
    def _provide_memory_settings(self) -> MemorySettings:
        return MemorySettings()

    @multiprovider
    def _provide_message_transformers(
        self,
        retrieve_memory_transformer: _RetrieveMemoryTransformer,
    ) -> list[MessagesTransformer]:
        return [retrieve_memory_transformer]

    @multiprovider
    def _provide_skills_to_inject(self) -> BUILTIN_SKILLS_TO_INJECT:
        return [("dial-memory", "call_synthetic_dial_memory_0001")]
