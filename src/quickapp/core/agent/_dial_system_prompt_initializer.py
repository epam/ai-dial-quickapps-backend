from injector import inject

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.exceptions import InitializationException, OrchestratorSystemPromptException
from quickapp.config.application import ApplicationConfig
from quickapp.config.prompt import DialSystemPromptConfig
from quickapp.dial_core_services.dial_prompt_loader import DialPromptLoader
from quickapp.dial_core_services.exceptions import DialPromptLoadError


@inject
class _DialSystemPromptInitializer(CompletionInitializer):
    """Loads the orchestrator's `dial` system prompt; the request fails if it cannot be loaded."""

    # Before _DialAppResolver (-100), so a missing prompt fails the request before other
    # initializers call DIAL.
    order = -200

    def __init__(self, app_config: ApplicationConfig, prompt_loader: DialPromptLoader) -> None:
        self._app_config = app_config
        self._prompt_loader = prompt_loader
        self._initialization_exceptions: list[InitializationException] = []

    async def initialize(self) -> None:
        system_prompt = self._app_config.orchestrator.system_prompt
        if not isinstance(system_prompt, DialSystemPromptConfig):
            return
        try:
            system_prompt.content = await self._prompt_loader.load(system_prompt.path)
        except DialPromptLoadError as e:
            exception = OrchestratorSystemPromptException(message=str(e), path=system_prompt.path)
            self._initialization_exceptions.append(exception)
            raise exception from e

    @property
    def initialization_exceptions(self) -> list[InitializationException]:
        return self._initialization_exceptions
