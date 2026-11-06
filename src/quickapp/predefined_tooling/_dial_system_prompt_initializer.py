from aidial_client import AsyncDial
from injector import ProviderOf, inject

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.dial_system_prompt import DialSystemPromptError, fetch_dial_system_prompt
from quickapp.common.exceptions import ConfigResolutionException
from quickapp.config.application import ApplicationConfig
from quickapp.config.prompt import DialSystemPromptConfig
from quickapp.predefined_tooling._predefined_tooling_context import _PredefinedToolingContext


@inject
class _DialSystemPromptInitializer(CompletionInitializer):
    """Loads the orchestrator's `dial` system prompt, failing fast like a missing predefined one."""

    order = -200

    def __init__(
        self,
        config_provider: ProviderOf[ApplicationConfig],
        dial_client: AsyncDial,
        context: _PredefinedToolingContext,
    ) -> None:
        self._config_provider = config_provider
        self._dial_client = dial_client
        self._context = context

    async def initialize(self) -> None:
        system_prompt = self._config_provider.get().orchestrator.system_prompt
        if not isinstance(system_prompt, DialSystemPromptConfig):
            return
        try:
            system_prompt.content = await fetch_dial_system_prompt(
                self._dial_client, system_prompt.path
            )
        except DialSystemPromptError as e:
            exception = ConfigResolutionException(message=str(e), template_name=system_prompt.path)
            self._context.append_exception(exception)
            raise exception from e
