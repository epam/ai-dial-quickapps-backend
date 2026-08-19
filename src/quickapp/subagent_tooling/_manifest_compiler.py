import logging

from quickapp.config.application import ApplicationConfig
from quickapp.config.prompt import CustomSystemPromptConfig
from quickapp.config.subagent import SubagentConfig

from ._exceptions import SubagentToolSetResolutionError

logger = logging.getLogger(__name__)


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
        manifest.tool_sets = [ts for ts in manifest.tool_sets if ts.name in allowed]
        unknown = allowed - {ts.name for ts in parent.tool_sets}
        if unknown:
            logger.warning(
                "Subagent %s references unknown tool sets: %s", subagent.name, sorted(unknown)
            )
        if allowed and not manifest.tool_sets:
            # A subagent that asked for tools and got none would run anyway and
            # confabulate an answer from the task text alone. Fail instead.
            raise SubagentToolSetResolutionError(
                subagent_name=subagent.name,
                requested=sorted(allowed),
                available=sorted(ts.name for ts in parent.tool_sets),
            )

    # Depth 1: a spoke cannot spawn. Starters are a coordinator-only concern.
    manifest.subagents = None
    manifest.starters = None
    manifest.conversation_starters = None

    return manifest
