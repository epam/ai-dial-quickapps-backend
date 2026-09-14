import logging

from aidial_sdk.chat_completion import Message
from injector import ProviderOf, inject

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.common.synthetic_injection.staged_tool_synthetic_injector import (
    StagedToolSyntheticInjector,
)
from quickapp.config.application import StageDisplayLevel
from quickapp.skill_invocation._invoked_skills_context import _InvokedSkillsContext
from quickapp.skill_invocation._skill_reference import skill_name_from_url
from quickapp.skills import ResolvedSkill
from quickapp.skills._tool_configs import SKILL_READER_TOOL_NAME

logger = logging.getLogger(__name__)

# Fixed on purpose: the resolver's reason is operator detail that belongs in the
# "Initialization issues" stage and the logs. A varying, internals-shaped string
# gives the model something to improvise on.
_LOAD_FAILED = (
    "Error: the user's skill `{name}` could not be loaded. The reason is shown to the user."
)


class _SkillInvocationInjector(StagedToolSyntheticInjector):
    """Turns the skill the user invoked on this message into a synthetic ``read_skill``
    call and result, so the model always starts the turn with the manifest in context.

    Everything but the arguments comes from ``StagedToolSyntheticInjector``: it looks
    the tool up by its function name and runs it. The stage is raised to ``INFO`` —
    the invocation is something the user did explicitly, so the ordinary
    "Reading Skill: <name>" stage belongs in the response.

    ``APPEND_IF_CHANGED`` puts the pair after the first user message, the same slot the
    built-in file-transfer skill uses. It runs only on the turn the pick is made
    (``should_inject``); afterwards the pair is restored from
    ``state.tool_execution_history`` like any other tool result, so the model keeps the
    manifest it first saw and ``read_skill`` is never re-run for it.
    """

    stage_level = StageDisplayLevel.INFO

    @inject
    def __init__(
        self,
        context: _InvokedSkillsContext,
        tools: list[StagedBaseTool],
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]],
    ) -> None:
        super().__init__(tools, enrichers_provider)
        self.__context = context

    async def should_inject(self, messages: list[Message]) -> bool:
        return self.__context.current_pick_url is not None

    async def get_tool_name(self) -> str:
        return SKILL_READER_TOOL_NAME

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.APPEND_IF_CHANGED

    async def get_arguments(self) -> dict:
        return {"skill_name": self.__skill_name()}

    async def get_content(self, messages: list[Message]) -> str | None:
        """Delegate to the tool, except for a skill that never made it into the registry.

        Running ``read_skill`` for one would only produce the tool's own "not found",
        so the fixed sentence is returned directly instead.
        """
        if self.__resolved_skill() is None:
            return _LOAD_FAILED.format(name=self.__skill_name())
        return await super().get_content(messages)

    def __skill_name(self) -> str:
        """The picked skill's own name, or the URL's last segment when it failed to
        resolve — which is what the name would almost certainly have been, and gives
        the model something to name in its apology."""
        skill = self.__resolved_skill()
        if skill is not None:
            return skill.metadata.name
        return skill_name_from_url(self.__context.current_pick_url or "")

    def __resolved_skill(self) -> ResolvedSkill | None:
        url = self.__context.current_pick_url
        return self.__context.find_skill(url) if url is not None else None
