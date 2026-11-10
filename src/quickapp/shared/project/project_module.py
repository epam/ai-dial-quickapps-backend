from fastapi_injector import request_scope
from injector import Binder, Module, ProviderOf, multiprovider, singleton

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.exceptions import InitializationException
from quickapp.common.preview import preview_module
from quickapp.shared.project._project_access_preflight import _ProjectAccessPreflight
from quickapp.shared.project._project_instructions import _ProjectInstructions
from quickapp.shared.project._project_prompt_provider import _ProjectPromptProvider
from quickapp.shared.project._settings import ProjectSettings


@preview_module
class ProjectModule(Module):
    """Project chats (``x-project-id``): the access preflight and the project prompt section
    (which loads ``PROJECT.md``).

    ``PROJECT_CONTEXT`` itself is provided by ``AppModule``; both parts are no-ops when it
    is ``None``. Registered in ``shared_module`` right after ``core_module``, so the prompt
    section follows the app's own system prompt.
    """

    def configure(self, binder: Binder) -> None:
        binder.bind(ProjectSettings, to=ProjectSettings, scope=singleton)
        binder.bind(_ProjectInstructions, to=_ProjectInstructions, scope=request_scope)
        binder.bind(_ProjectAccessPreflight, to=_ProjectAccessPreflight, scope=request_scope)
        binder.bind(_ProjectPromptProvider, to=_ProjectPromptProvider, scope=request_scope)

    @multiprovider
    def _provide_initializers(
        self, preflight: ProviderOf[_ProjectAccessPreflight]
    ) -> list[CompletionInitializer]:
        return [preflight.get()]

    @multiprovider
    def _provide_prompt_parts(
        self, prompt_provider: ProviderOf[_ProjectPromptProvider]
    ) -> list[PromptPartProvider]:
        return [prompt_provider.get()]

    @multiprovider
    def _provide_initialization_exceptions(
        self, instructions: ProviderOf[_ProjectInstructions]
    ) -> list[InitializationException]:
        # Resolved by _InitializationErrorHandler after the initializers have run.
        return instructions.get().exceptions
