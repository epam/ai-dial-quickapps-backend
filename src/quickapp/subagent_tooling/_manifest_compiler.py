import logging

from quickapp.config.application import ApplicationConfig
from quickapp.config.prompt import CustomSystemPromptConfig
from quickapp.config.subagent import SubagentConfig
from quickapp.config.toolsets.predefined import PredefinedToolSet
from quickapp.config.toolsets.toolset import ToolSet

from ._exceptions import SubagentToolSetResolutionError

logger = logging.getLogger(__name__)


def _tool_set_name(tool_set: ToolSet) -> str | None:
    """The name of a resolved tool set, or ``None`` for a predefined reference.

    A ``PredefinedToolSet`` is a template pointer with a ``template_name`` and no
    ``name``. ``_PredefinedConfigResolver`` expands every one into a concrete tool set
    during config resolution, well before a subagent manifest is compiled — so this
    returns ``None`` only for a shape that cannot reach us at runtime. The branch exists
    because the declared type of ``ApplicationConfig.tool_sets`` still admits it.
    """
    if isinstance(tool_set, PredefinedToolSet):
        return None
    return tool_set.name


def tool_set_names(config: ApplicationConfig) -> list[str]:
    """Names of the app's resolved tool sets, sorted."""
    return sorted(name for ts in config.tool_sets if (name := _tool_set_name(ts)) is not None)


def unknown_tool_sets(parent: ApplicationConfig, subagent: SubagentConfig) -> list[str]:
    """Tool set names a subagent declares that the app does not define.

    One definition, two call sites with deliberately different severities:
    ``SubagentToolingModule`` turns a non-empty result into an initialization error, so
    the builder sees the typo by name before any spawn; ``compile_subagent_manifest``
    only logs, because by the time it runs initialization has already vetoed the app.
    """
    return sorted(set(subagent.tool_sets or []) - set(tool_set_names(parent)))


def compile_subagent_manifest(
    parent: ApplicationConfig, subagent: SubagentConfig
) -> ApplicationConfig:
    """Compile a declared subagent type into a full manifest the orchestrator can run.

    The spoke is just a QuickApp with a narrowed manifest — which is why the tool
    allowlist needs no dedicated filtering machinery.
    """
    manifest = parent.model_copy(deep=True)

    manifest.orchestrator.system_prompt = CustomSystemPromptConfig(
        content=subagent.system_prompt, variables={}
    )
    if subagent.max_iterations is not None:
        manifest.orchestrator.max_iterations = subagent.max_iterations
    if subagent.deployment_id is not None:
        manifest.orchestrator.deployment.deployment_id = subagent.deployment_id

    if subagent.tool_sets is not None:
        allowed = set(subagent.tool_sets)
        manifest.tool_sets = [ts for ts in manifest.tool_sets if _tool_set_name(ts) in allowed]
        unknown = unknown_tool_sets(parent, subagent)
        if unknown:
            logger.warning("Subagent %s references unknown tool sets: %s", subagent.name, unknown)
        if allowed and not manifest.tool_sets:
            # A subagent that asked for tools and got none would run anyway and
            # confabulate an answer from the task text alone. Fail instead.
            raise SubagentToolSetResolutionError(
                subagent_name=subagent.name,
                requested=sorted(allowed),
                available=tool_set_names(parent),
            )

    # Depth 1: a spoke cannot spawn. Starters are a coordinator-only concern.
    manifest.subagents = None
    manifest.starters = None
    manifest.conversation_starters = None

    return manifest
