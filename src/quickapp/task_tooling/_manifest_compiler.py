from quickapp.config.application import ApplicationConfig
from quickapp.config.hooks import HookEvent
from quickapp.config.prompt import CustomSystemPromptConfig
from quickapp.config.run_task import RunTaskConfig

from ._task_prompt import TASK_SYSTEM_PROMPT

_APP_RULES_HEADING = "## Rules from the application"
# Only these hook events run inside a task; a new event must be added deliberately.
_TASK_HOOK_EVENTS = frozenset({HookEvent.ON_REQUEST_START})


def _task_system_prompt(app_prompt: str | None) -> str:
    """The task prompt, then the app's own prompt so its rules still apply."""
    if not app_prompt or not app_prompt.strip():
        return TASK_SYSTEM_PROMPT
    return f"{TASK_SYSTEM_PROMPT}\n\n{_APP_RULES_HEADING}\n\n{app_prompt.strip()}"


def compile_task_manifest(
    parent: ApplicationConfig, config: RunTaskConfig, explicit_tools: bool
) -> ApplicationConfig:
    """The delegating app's manifest, narrowed into the one a task runs.

    Contexts, skills and ``on_request_start`` hooks are inherited; other hook events
    are not, so ``on_completion`` fires once per user turn. The app's system prompt
    follows the task prompt. Fields the compiler doesn't touch are inherited.
    ``explicit_tools`` turns tool discovery off, so a named deferred tool becomes a regular
    one and nothing outside the allowlist can be loaded through ``internal_tool_search``.
    """
    manifest = parent.model_copy(deep=True)

    manifest.orchestrator.system_prompt = CustomSystemPromptConfig(
        content=_task_system_prompt(parent.orchestrator.system_prompt.content), variables={}
    )
    if config.max_iterations is not None:
        manifest.orchestrator.max_iterations = config.max_iterations
    if explicit_tools:
        manifest.orchestrator.tool_discovery = None

    # Depth 1: a task cannot run tasks.
    if manifest.features is not None:
        manifest.features.run_task = None
    manifest.hooks = [
        hook for hook in manifest.hooks or [] if hook.event in _TASK_HOOK_EVENTS
    ] or None
    # Starters are a user-facing feature.
    manifest.starters = None
    manifest.conversation_starters = None

    return manifest
