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
from quickapp.skills.invocation._invoked_skills_context import _InvokedSkillsContext
from quickapp.skills.invocation._settings import SkillInvocationSettings
from quickapp.skills.invocation._skill_reference import collect_picks, skill_name_from_url
from quickapp.skills.skill_resolver import DialSkillResourceResolver

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
    in parallel by the resolver.
    """

    def __init__(
        self,
        messages: REQUEST_MESSAGES,
        resolver: DialSkillResourceResolver,
        context: _InvokedSkillsContext,
        settings: SkillInvocationSettings,
    ) -> None:
        self._messages = messages
        self._resolver = resolver
        self._context = context
        self._settings = settings

    async def initialize(self) -> None:
        collected = collect_picks(self._messages)
        picks = collected.by_ordinal
        last_ordinal = sum(1 for message in self._messages if message.role == Role.USER) - 1
        self._context.set_current_pick_url(picks.get(last_ordinal))

        self.__report_ignored(collected.ignored_by_ordinal, last_ordinal)
        if not picks:
            return

        # The cap is spent newest-first, so the pick made on the message being
        # answered is never the one dropped.
        urls = [picks[ordinal] for ordinal in sorted(picks)][-self._settings.max_skills :]

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

    def __report_ignored(self, ignored_by_ordinal: dict[int, list[str]], last_ordinal: int) -> None:
        """Tell the user when the message being answered invoked more than one skill.

        Only one skill may be invoked per message. Older turns are left to the log,
        like every other historical problem, so the stage does not repeat an issue
        the user can no longer act on.
        """
        ignored = ignored_by_ordinal.get(last_ordinal)
        if not ignored:
            return
        names = ", ".join(skill_name_from_url(url) for url in ignored)
        self._context.append_exception(
            SkillInitializationException(
                reason=(
                    "Only one skill can be invoked per message;"
                    f" the first one was loaded and these were ignored: {names}"
                ),
                severity="warning",
            )
        )

    def __report(self, exceptions: list[SkillInitializationException]) -> None:
        """Surface only what went wrong with this turn's pick.

        Every pick is resolved again on every turn, so reporting all of them would
        repeat the same issues until the conversation ends. The model still learns
        about a failed pick from its error result.
        """
        current = self._context.current_pick_url
        for exception in exceptions:
            if exception.url is None or exception.url == current:
                self._context.append_exception(exception)
            else:
                logger.debug(
                    "Skipping a skill picked on an earlier turn that could not be loaded: %s",
                    skill_name_from_url(exception.url),
                )
