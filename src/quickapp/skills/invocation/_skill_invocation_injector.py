import logging

from aidial_sdk.chat_completion import Message
from injector import ProviderOf, inject

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.common.synthetic_injection.multi_synthetic_tool_call_injector import (
    MultiSyntheticToolCallInjector,
    SyntheticCall,
)
from quickapp.common.synthetic_injection.staged_tool_lookup import (
    build_staged_tool_index,
    find_staged_tool,
)
from quickapp.common.tool_names import INTERNAL_SKILLS_READ_SKILL_TOOL_NAME
from quickapp.config.application import StageDisplayLevel
from quickapp.skills.invocation._invoked_skills_context import _InvokedSkillsContext
from quickapp.skills.invocation._skill_reference import skill_name_from_url

logger = logging.getLogger(__name__)

# Fixed on purpose: the resolver's reason is operator detail that belongs in the
# "Initialization issues" stage and the logs. A varying, internals-shaped string
# gives the model something to improvise on.
_LOAD_FAILED = (
    "Error: the user's skill `{name}` could not be loaded. The reason is shown to the user."
)

# The real call id is only known after every call's content is hashed (see
# MultiSyntheticToolCallInjector.transform), which happens after get_content runs.
# This probe id is used only for the tool's own logging/timers, never surfaced.
_ARUN_SYNTHETIC_CALL_ID = "synthetic_injection_probe"


class _SkillInvocationInjector(MultiSyntheticToolCallInjector):
    """Turns every skill the user invoked on this message into one synthetic
    assistant turn with a parallel ``read_skill`` call per skill, so the model
    always starts the turn with every picked manifest already in context.

    A resolved skill's call is run through the real ``read_skill`` tool, byte
    identical to what a model-initiated call returns. A skill that failed to
    resolve gets a fixed error result instead — running the tool for one would
    only reproduce its own "not found".

    The stage is raised to ``INFO`` for a resolved skill — the invocation is
    something the user did explicitly, so the ordinary "Reading Skill: <name>"
    stage belongs in the response.

    ``MultiSyntheticToolCallInjector`` puts the turn after the first user message,
    the same slot the built-in file-transfer skill uses, and it runs only on the
    turn the picks are made (``get_calls`` returns nothing otherwise).

    How long the turn survives depends on *which* turn made the picks.
    ``Orchestrator._build_tool_execution_history`` persists only what follows the
    **last** user message, so picks made on the first user message are stored and
    come back from ``state.tool_execution_history`` on every later turn, like any
    other tool result. Picks made on any later message land ahead of that boundary,
    are never persisted, and are therefore in context for their own turn only — the
    skills stay listed in ``<available_skills>`` and readable through ``read_skill``,
    but the model is no longer handed the manifests unprompted. Accepted for phase
    1a; the file-transfer injector does not hit this because it re-injects on every
    turn instead of relying on persistence.
    """

    stage_level = StageDisplayLevel.INFO
    call_id_prefix = "synth_skill_invocation_"

    @inject
    def __init__(
        self,
        context: _InvokedSkillsContext,
        tools: list[StagedBaseTool],
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]],
    ) -> None:
        super().__init__(enrichers_provider)
        self.__context = context
        self.__tools = build_staged_tool_index(tools)

    async def get_calls(self, messages: list[Message]) -> list[SyntheticCall]:
        urls = self.__context.current_pick_urls
        if not urls:
            return []
        tool = find_staged_tool(
            self.__tools, INTERNAL_SKILLS_READ_SKILL_TOOL_NAME, logger, "_SkillInvocationInjector"
        )
        if tool is None:
            return []
        return [
            SyntheticCall(
                tool_name=INTERNAL_SKILLS_READ_SKILL_TOOL_NAME,
                arguments={"skill_name": self.__skill_name(url)},
                payload=url,
            )
            for url in urls
        ]

    async def get_content(self, call: SyntheticCall, index: int, messages: list[Message]) -> str:
        url = call.payload
        if self.__context.find_skill(url) is None:
            return _LOAD_FAILED.format(name=self.__skill_name(url))

        tool = self.__tools[call.tool_name]
        result = await tool.arun(
            _ARUN_SYNTHETIC_CALL_ID, stage_level=self.stage_level, **call.arguments
        )
        return result.content

    def __skill_name(self, url: str) -> str:
        """The picked skill's own name, or the URL's last segment when it failed to
        resolve — which is what the name would almost certainly have been, and gives
        the model something to name in its apology."""
        skill = self.__context.find_skill(url)
        return skill.metadata.name if skill is not None else skill_name_from_url(url)
