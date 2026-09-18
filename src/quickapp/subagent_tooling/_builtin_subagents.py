"""The instructions and framing for the built-in ``general-purpose`` subagent.

Mirrors Claude Code's `general-purpose` agent: nothing to declare, and the caller
scopes each spawn at the moment it delegates rather than the builder foreseeing every
helper up front. An app builder may replace the prompt below through
`features.subagents.general_purpose.system_prompt`.
"""

from quickapp.config.subagent import (
    GENERAL_PURPOSE_SUBAGENT_NAME,
    GeneralPurposeSubagentConfig,
    SubagentConfig,
)

GENERAL_PURPOSE_DESCRIPTION = (
    "General-purpose subagent for researching complex questions, searching for "
    "information, and executing multi-step tasks. Use it when a sub-task takes several "
    "tool calls whose intermediate results you do not need to see. You choose which "
    "tool sets it gets for each task via `tool_sets`."
)

GENERAL_PURPOSE_SYSTEM_PROMPT = """\
You are an autonomous subagent working on one self-contained task for a coordinating \
agent.

You are working alone. There is no user to ask and no coordinator to check with: you \
cannot ask clarifying questions, and no one will answer if you try. When the task is \
ambiguous, choose the most reasonable interpretation, act on it, and say which \
interpretation you took in your report.

Use the tools available to you to gather what the task needs rather than answering from \
assumption. Those tools were chosen for this task specifically, so they are the ones to \
reach for. Work until the task is done or you have established that it cannot be done.

Your final message is the entire report the coordinator will see. Nothing else you do — \
no tool call, no intermediate note — reaches it. So make that message stand on its own: \
state the answer, the evidence behind it, and anything you could not determine. Never \
end with an acknowledgement like "done" or "I've finished" — that tells the coordinator \
nothing.\
"""


def general_purpose_subagent(
    config: GeneralPurposeSubagentConfig, tool_sets: list[str]
) -> SubagentConfig:
    """Materialize the built-in subagent for one spawn, in the declared-type shape.

    The only thing the coordinator decides per call is ``tool_sets``; everything else
    comes from the app's tuning or the built-in defaults. Once shaped like a declared
    type, a general-purpose spawn takes the same path through the spawner.
    """
    return SubagentConfig(
        name=GENERAL_PURPOSE_SUBAGENT_NAME,
        description=GENERAL_PURPOSE_DESCRIPTION,
        system_prompt=config.system_prompt or GENERAL_PURPOSE_SYSTEM_PROMPT,
        tool_sets=tool_sets,
        deployment_id=config.deployment_id,
        max_iterations=config.max_iterations,
    )
