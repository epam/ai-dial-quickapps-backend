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
from quickapp.skill_invocation._skill_reference import collect_picks, skill_name_from_url

logger = logging.getLogger(__name__)


@inject
class _SkillInvocationInitializer(CompletionInitializer):
    """Resolves every skill picked anywhere in the conversation, so the merged skill
    set is available to ``_AddSystemPromptTransformer``.

    An initializer rather than a transformer: ``SkillsRegistry`` caches its merge on
    first call, and that call comes from ``_AddSystemPromptTransformer``.

    Every pick is re-resolved on every turn. That is what keeps a skill picked on
    turn 1 listed in ``<available_skills>`` on turn 4 and its bundled files readable.
    The cost is one Core fetch per picked skill per turn, bounded by the cap and run
    in parallel by ``DialSkillResolver``.
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
        collected = collect_picks(self._messages, self._settings.max_skills_per_message)
        picks_by_ordinal = collected.by_ordinal
        last_ordinal = sum(1 for message in self._messages if message.role == Role.USER) - 1
        current_urls = picks_by_ordinal.get(last_ordinal, [])
        self._context.set_current_pick_urls(current_urls)

        self.__report_overflow(collected.overflow_by_ordinal, last_ordinal)

        # Oldest first, in chip order within each message.
        all_urls = [
            url for ordinal in sorted(picks_by_ordinal) for url in picks_by_ordinal[ordinal]
        ]
        if not all_urls:
            return

        # The cap is spent newest-first, so a pick made on the message being
        # answered is never the one dropped.
        urls = all_urls[-self._settings.max_skills :]

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
        self.__report(output.exceptions, current_urls)

    def __report_overflow(
        self, overflow_by_ordinal: dict[int, list[str]], last_ordinal: int
    ) -> None:
        """Tell the user when the message being answered invoked more chips than
        ``max_skills_per_message``.

        Older turns are left to the log, like every other historical problem, so the
        stage does not repeat an issue the user can no longer act on.
        """
        overflow = overflow_by_ordinal.get(last_ordinal)
        if not overflow:
            return
        names = ", ".join(skill_name_from_url(url) for url in overflow)
        self._context.append_exception(
            SkillInitializationException(
                reason=(
                    f"At most {self._settings.max_skills_per_message} skills can be"
                    f" invoked per message; these were ignored: {names}"
                ),
                severity="warning",
            )
        )

    def __report(
        self, exceptions: list[SkillInitializationException], current_urls: list[str]
    ) -> None:
        """Surface only what went wrong with this turn's picks.

        Every pick is resolved again on every turn, so reporting all of them would
        repeat the same issues until the conversation ends. The model still learns
        about a failed pick from its error result.
        """
        current = set(current_urls)
        for exception in exceptions:
            if exception.url is None or exception.url in current:
                self._context.append_exception(exception)
            else:
                logger.debug(
                    "Skipping a skill picked on an earlier turn that could not be loaded: %s",
                    skill_name_from_url(exception.url),
                )
