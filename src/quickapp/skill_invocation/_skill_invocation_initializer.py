import logging

from aidial_sdk.chat_completion import Role
from injector import inject

from quickapp.common import REQUEST_MESSAGES
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.exceptions import (
    SkillCatastrophicInitializationException,
    SkillInitializationException,
)
from quickapp.config.skill import DialSkillConfig
from quickapp.dial_skills import DialSkillResolver
from quickapp.skill_invocation._invoked_skills_context import _InvokedSkillsContext
from quickapp.skill_invocation._settings import SkillInvocationSettings
from quickapp.skill_invocation._skill_reference import collect_skill_urls, message_skill_urls

logger = logging.getLogger(__name__)


@inject
class _SkillInvocationInitializer(CompletionInitializer):
    """Resolves every skill picked anywhere in the conversation, so the merged skill
    set is available to ``_AddSystemPromptTransformer``.

    An initializer rather than a transformer: ``SkillsRegistry`` caches its merge on
    first call, and that call comes from ``_AddSystemPromptTransformer``.

    Every historical pick is re-resolved on every turn. That is what keeps a skill
    picked on turn 1 registered on turn 4, so its bundled files stay readable. The
    cost is one Core fetch per picked skill per turn, bounded by the cap and run in
    parallel by ``DialSkillResolver``.
    """

    def __init__(
        self,
        messages: REQUEST_MESSAGES,
        resolver: DialSkillResolver,
        context: _InvokedSkillsContext,
        settings: SkillInvocationSettings,
    ) -> None:
        self._messages = messages
        self._resolver = resolver
        self._context = context
        self._settings = settings

    async def initialize(self) -> None:
        self._context.set_current_turn_urls(self.__current_turn_urls())

        urls = collect_skill_urls(self._messages, self._settings.max_skills)
        if not urls:
            return

        try:
            output = await self._resolver.resolve([DialSkillConfig(url=url) for url in urls])
        except Exception as exc:
            logger.exception("User skill resolution failed")
            self._context.append_exception(
                SkillCatastrophicInitializationException(
                    reason=f"Failed to resolve user skills: {exc}"
                )
            )
            return

        self._context.set_resolved_skills(output.resolved)
        self.__report(output.exceptions)

    def __current_turn_urls(self) -> list[str]:
        """Chips of the message being answered — the only ones the injector acts on."""
        for message in reversed(self._messages):
            if message.role == Role.USER:
                return message_skill_urls(message)
        return []

    def __report(self, exceptions: list[SkillInitializationException]) -> None:
        """Surface only what went wrong with this turn's chips.

        Every historical pick is resolved again on every turn, so reporting all of
        them would repeat the same issues until the conversation ends. The model
        still learns about a failed chip from its error result.
        """
        current = set(self._context.current_turn_urls)
        for exception in exceptions:
            if exception.url is None or exception.url in current:
                self._context.append_exception(exception)
            else:
                logger.info("A skill picked on an earlier turn could not be loaded")
