import logging

from quickapp.common.localized_string import resolve_localized
from quickapp.config.application import ApplicationConfig
from quickapp.config.prompt import CustomSystemPromptConfig
from quickapp.config.subagent import SubagentConfig
from quickapp.config.toolsets.predefined import PredefinedToolSet
from quickapp.config.toolsets.toolset import ToolSet

from ._exceptions import SubagentToolSetResolutionError

logger = logging.getLogger(__name__)


def tool_set_name(tool_set: ToolSet) -> str | None:
    """The name of a resolved tool set, or ``None`` for a predefined reference.

    A ``PredefinedToolSet`` is a template pointer with a ``template_name`` and no
    ``name``. ``_PredefinedConfigResolver`` expands every one into a concrete tool set
    during config resolution, well before a subagent manifest is compiled — so this
    returns ``None`` only for a shape that cannot reach us at runtime. The branch exists
    because the declared type of ``ApplicationConfig.tool_sets`` still admits it.

    A tool set name is a ``LocalizedString``, so it may be a per-locale mapping rather
    than a plain string. Resolved with no locale — the default-locale form — because the
    coordinator selects a tool set by an identifier it read out of the `task` tool's
    schema, and that identifier must not shift with the caller's Accept-Language.
    """
    if isinstance(tool_set, PredefinedToolSet):
        return None
    return resolve_localized(tool_set.name)


def selectable_tool_sets(config: ApplicationConfig) -> list[ToolSet]:
    """The tool sets a spoke may be given, in manifest order.

    Disabled tool sets are excluded: they produce no tools, so handing one to a spoke
    would only run it with fewer tools than intended and let it answer from the task
    text alone.
    """
    return [
        ts
        for ts in config.tool_sets
        if not isinstance(ts, PredefinedToolSet) and ts.enabled and tool_set_name(ts)
    ]


def tool_set_names(config: ApplicationConfig) -> list[str]:
    """Names of the app's selectable tool sets, in manifest order.

    One definition, three call sites: it fills the `task` tool's `tool_sets` enum, it
    vets what the coordinator passed back for a general-purpose spawn, and it checks a
    declared type's allowlist at initialization.
    """
    return [name for ts in selectable_tool_sets(config) if (name := tool_set_name(ts))]


def unknown_tool_sets(parent: ApplicationConfig, subagent: SubagentConfig) -> list[str]:
    """Tool set names a subagent declares that the app does not offer.

    Two call sites: ``SubagentToolingModule`` turns a non-empty result into an
    initialization issue the builder sees by name; ``compile_subagent_manifest`` logs
    it, since the initialization stage only renders the issue and the run continues.
    """
    return sorted(set(subagent.tool_sets or []) - set(tool_set_names(parent)))


def compile_subagent_manifest(
    parent: ApplicationConfig, subagent: SubagentConfig
) -> ApplicationConfig:
    """Compile one subagent plus the coordinator's manifest into one the orchestrator can run.

    The spoke is just a QuickApp with a narrowed manifest — which is why the tool
    allowlist needs no dedicated filtering machinery. ``subagent`` is either a declared
    type or the general-purpose one materialized for this call.
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
        manifest.tool_sets = [
            ts for ts in selectable_tool_sets(manifest) if tool_set_name(ts) in allowed
        ]
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
    if manifest.features is not None:
        manifest.features.subagents = None
    manifest.starters = None
    manifest.conversation_starters = None

    return manifest
