from injector import ProviderOf, inject

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.config.application import ApplicationConfig

_INSTRUCTION = (
    "When you need to read, search, write, edit, or delete a text file stored in DIAL "
    "(URL starts with `files/`), use the dedicated `internal_text_file_*` tools "
    "instead of fetching the URL via an MCP or HTTP tool"
)


@inject
class _TextFileToolPromptProvider(PromptPartProvider):
    def __init__(self, config_provider: ProviderOf[ApplicationConfig]):
        self.__config_provider = config_provider

    async def get_prompt_part(self) -> str:
        app_config = self.__config_provider.get()
        cfg = app_config.features.text_file_tools if app_config.features else None
        if cfg is None:
            return ""
        return _INSTRUCTION
