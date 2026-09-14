import logging

from aidial_sdk.chat_completion import Message
from injector import ProviderOf, inject

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    build_synthetic_pair,
    has_synthetic_pair_with_prefix,
    make_synthetic_call_id,
    make_synthetic_call_id_prefix,
)
from quickapp.common.tool_message_utils import after_last_user_idx
from quickapp.skill_invocation._invoked_skills_context import _InvokedSkillsContext
from quickapp.skill_invocation._skill_reference import skill_name_from_url
from quickapp.skills._tool_configs import SKILL_READER_TOOL_NAME

logger = logging.getLogger(__name__)

_ARUN_SYNTHETIC_CALL_ID = "skill_invocation"

# Fixed on purpose: the resolver's reason is operator detail that belongs in the
# "Initialization issues" stage and the logs. A varying, internals-shaped string
# gives the model something to improvise on.
_LOAD_FAILED = (
    "Error: the user's skill `{name}` could not be loaded. The reason is shown to the user."
)


class _SkillInvocationInjector(MessagesTransformer):
    """Inserts one synthetic ``read_skill`` call/result pair per distinct chip on the
    message being answered, directly after that message.

    The explicit index keeps the pairs ahead of any transformer that appends to the
    end of the list, whatever the module order.

    Earlier turns need nothing: their pair was inserted after the user message of
    their own turn, ``Orchestrator`` persisted it into
    ``state.tool_execution_history`` and ``_MessagesSetup`` restored it.
    """

    @inject
    def __init__(
        self,
        context: _InvokedSkillsContext,
        tools_provider: ProviderOf[list[StagedBaseTool]],
    ) -> None:
        self._context = context
        self._tools_provider = tools_provider

    async def transform(self, messages: list[Message]) -> list[Message]:
        urls = self._context.current_turn_urls
        if not urls:
            return messages

        index = after_last_user_idx(messages)
        if index is None:
            return messages

        pairs: list[Message] = []
        injected_prefixes: set[str] = set()
        for url in urls:
            skill = self._context.find_skill(url)
            name = skill.metadata.name if skill is not None else skill_name_from_url(url)
            arguments = {"skill_name": name}
            prefix = make_synthetic_call_id_prefix(SKILL_READER_TOOL_NAME, arguments)
            # A pair for the same tool and arguments is already there: the model keeps
            # the manifest from the turn that first picked the skill, and a request
            # never carries two pairs sharing a tool_call_id.
            if prefix in injected_prefixes or has_synthetic_pair_with_prefix(messages, prefix):
                continue

            if skill is None:
                content: str | None = _LOAD_FAILED.format(name=name)
            else:
                content = await self.__read_skill(name)
            if content is None:
                continue

            call_id = make_synthetic_call_id(SKILL_READER_TOOL_NAME, arguments, content)
            pairs.extend(build_synthetic_pair(SKILL_READER_TOOL_NAME, call_id, arguments, content))
            injected_prefixes.add(prefix)

        if not pairs:
            return messages
        return messages[:index] + pairs + messages[index:]

    async def __read_skill(self, skill_name: str) -> str | None:
        """Run the real ``read_skill`` tool, so the result is byte-identical to a
        model-initiated call, ``<skill_files>`` included.

        ``arun`` is called *without* ``stage_level`` so it defaults to ``INFO``, as it
        does in ``tool_executor``: the invocation is something the user did, so its
        stage belongs in the response.
        """
        tool = self.__find_skill_reader()
        if tool is None:
            logger.warning("Skill reader tool is unavailable; skipping a skill invocation")
            return None
        result = await tool.arun(_ARUN_SYNTHETIC_CALL_ID, skill_name=skill_name)
        return result.content

    def __find_skill_reader(self) -> StagedBaseTool | None:
        return next(
            (
                tool
                for tool in self._tools_provider.get()
                if tool.tool_config.open_ai_tool.function.name == SKILL_READER_TOOL_NAME
            ),
            None,
        )
