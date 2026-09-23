import logging

from aidial_sdk.chat_completion import Message
from injector import ProviderOf, inject

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    MultiSyntheticToolCallInjector,
)
from quickapp.common.tool_names import INTERNAL_SKILLS_READ_SKILL_TOOL_NAME
from quickapp.config.application import StageDisplayLevel
from quickapp.skills.invocation._invoked_skills_context import _InvokedSkillsContext
from quickapp.skills.invocation._skill_reference import skill_name_from_url
from quickapp.skills.skills_provider import ResolvedSkill

logger = logging.getLogger(__name__)

# Fixed on purpose: the resolver's reason is operator detail that belongs in the
# "Initialization issues" stage and the logs. A varying, internals-shaped string
# gives the model something to improvise on.
_LOAD_FAILED = (
    "Error: the user's skill `{name}` could not be loaded. The reason is shown to the user."
)


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
        self.__tools: dict[str, StagedBaseTool] = {
            tool.tool_config.open_ai_tool.function.name: tool for tool in tools
        }

    async def get_calls(self, messages: list[Message]) -> list[tuple[str, dict]]:
        urls = self.__context.current_pick_urls
        if not urls:
            return []
        if INTERNAL_SKILLS_READ_SKILL_TOOL_NAME not in self.__tools:
            logger.warning(
                "_SkillInvocationInjector: tool '%s' not found in staged tools, skipping",
                INTERNAL_SKILLS_READ_SKILL_TOOL_NAME,
            )
            return []
        return [
            (INTERNAL_SKILLS_READ_SKILL_TOOL_NAME, {"skill_name": self.__skill_name(url)})
            for url in urls
        ]

    async def get_content(
        self, tool_name: str, arguments: dict, index: int, messages: list[Message]
    ) -> str:
        url = self.__context.current_pick_urls[index]
        if self.__context.find_skill(url) is None:
            return _LOAD_FAILED.format(name=self.__skill_name(url))

        tool = self.__tools[tool_name]
        result = await tool.arun(arguments["skill_name"], stage_level=self.stage_level, **arguments)
        return result.content

    def __skill_name(self, url: str) -> str:
        """The picked skill's own name, or the URL's last segment when it failed to
        resolve — which is what the name would almost certainly have been, and gives
        the model something to name in its apology."""
        skill = self.__context.find_skill(url)
        return skill.metadata.name if skill is not None else skill_name_from_url(url)
