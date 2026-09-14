from quickapp.common.localized_string import resolve_localized
from quickapp.config.application import ApplicationConfig
from quickapp.config.prompt import CustomSystemPromptConfig
from quickapp.config.subagent import SubagentsConfig
from quickapp.config.toolsets.predefined import PredefinedToolSet
from quickapp.config.toolsets.toolset import ToolSet

from ._builtin_subagents import GENERAL_PURPOSE_SYSTEM_PROMPT


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
    """The tool sets a spawn may be given, in manifest order.

    Disabled tool sets are excluded: they produce no tools, so offering one to the
    coordinator would only invite it to hand a spoke an empty set and wonder why.
    """
    return [
        ts
        for ts in config.tool_sets
        if not isinstance(ts, PredefinedToolSet) and ts.enabled and tool_set_name(ts)
    ]


def tool_set_names(config: ApplicationConfig) -> list[str]:
    """Names of the app's selectable tool sets, in manifest order.

    One definition, two call sites: it fills the `task` tool's `tool_sets` enum, and it
    vets what the coordinator actually passed back.
    """
    return [name for ts in selectable_tool_sets(config) if (name := tool_set_name(ts))]


def compile_subagent_manifest(
    parent: ApplicationConfig, config: SubagentsConfig, requested_tool_sets: list[str]
) -> ApplicationConfig:
    """Compile one spawn into a full manifest the orchestrator can run.

    The spoke is just a QuickApp with a narrowed manifest — which is why scoping its
    tools needs no dedicated filtering machinery.
    """
    manifest = parent.model_copy(deep=True)

    manifest.orchestrator.system_prompt = CustomSystemPromptConfig(
        content=config.system_prompt or GENERAL_PURPOSE_SYSTEM_PROMPT, variables={}
    )
    if config.max_iterations is not None:
        manifest.orchestrator.max_iterations = config.max_iterations
    if config.deployment_id is not None:
        manifest.orchestrator.deployment.deployment_id = config.deployment_id

    # A spoke gets the tool sets this spawn asked for and nothing else — never the
    # coordinator's whole surface. The names were vetted by `_SubagentTool` before we
    # got here, so an empty result means the caller deliberately asked for no tools.
    allowed = set(requested_tool_sets)
    manifest.tool_sets = [
        ts for ts in selectable_tool_sets(manifest) if tool_set_name(ts) in allowed
    ]

    # Depth 1: a spoke cannot spawn. Starters are a coordinator-only concern.
    if manifest.features is not None:
        manifest.features.subagents = None
    manifest.starters = None
    manifest.conversation_starters = None

    return manifest
